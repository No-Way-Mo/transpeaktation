"""Single coordinator: snapping -> candidates -> selection -> validation -> atomic reservation, and the assignment
lifecycle (provisional -> accepted -> active -> completed | cancelled | expired).

* Candidates are generated outside the lock; under the lock the forecast version is rechecked, the selector runs on
  the current ledger, the result is validated, persisted to SQLite and only then applied in memory.
* Plain previews allocate nothing. A deliberate recommendation reserves ONE provisional route (TTL 60 s); showing
  alternatives reserves nothing for them. Accepting another displayed alternative re-validates it; arbitrary paths
  are never accepted.
* An unavailable / invalid / too-slow selector falls back to the heuristic and the response says so.
* One coordinator process and one ledger. Do not scale by starting independent workers with separate ledgers.
"""
from __future__ import annotations

import threading
import time
import uuid

import numpy as np

from . import candidates as cand_mod
from . import selectors
from .config import Config
from .forecast_store import ForecastInvalid, ForecastSnapshot, ForecastStore
from .ledger import Ledger
from .network import RoadNetwork, Snap
from .schemas import (LIVE, Assignment, Candidate, RequestCandidates, RouteRequest, SelectionContext,
                      SelectionResult, iso)
from .scoring import ConcentrationScore
from .selectors.base import SelectorUnavailable, valid_indices
from .storage import Storage
from .timing import Infeasible, evaluate


class SelectorFailed(Exception):
    """Strict mode (benchmarks, RL evaluation): a selector fallback is an explicit failure, never silent."""


class Conflict(Exception):
    def __init__(self, reason: str, assignment: Assignment | None = None, status: int = 409):
        super().__init__(reason)
        self.reason, self.assignment, self.status = reason, assignment, status


class Coordinator:
    def __init__(self, cfg: Config, net: RoadNetwork, store: ForecastStore, storage: Storage, clock=time.time,
                 selector: str | None = None, strict: bool = False):
        self.cfg, self.net, self.store, self.storage, self.clock = cfg, net, store, storage, clock
        self.selector_name = selector or cfg.service.selector
        self.strict = strict
        self._selectors: dict = {}                        # cached instances: a policy checkpoint loads once
        if self.selector_name not in selectors.NAMES:
            raise ValueError(f"unknown selector {self.selector_name!r}")
        self.ledger = Ledger(net, cfg.ledger)
        self.score = ConcentrationScore(net, cfg.score)
        self.lock = threading.RLock()
        self.static_origin_ok = (net.outdeg > 0) & np.isin(net.static_availability, ["open", "alias"])
        self.recovered = self._recover()

    # ---- startup ----------------------------------------------------------------------------------------------------
    def _recover(self) -> int:
        live = self.storage.load_live()
        live = [a for a in live if a.network_version == self.net.version and all(r in self.net.pos for r in a.route)]
        with self.lock:
            self.ledger.apply(live)
            self.sweep()
        return len(live)

    # ---- helpers -----------------------------------------------------------------------------------------------------
    def _selector(self, name: str | None):
        name = name or self.selector_name
        if name not in self._selectors:
            self._selectors[name] = selectors.make(name, self.cfg)
        return self._selectors[name]

    def sweep(self, now: float | None = None) -> int:
        now = self.clock() if now is None else now
        with self.lock:
            exp = []
            for a in self.ledger.live():
                if a.expires_at <= now:
                    exp.append(self._next(a, status="expired", now=now))
            if exp:
                self._commit(exp)
            self.ledger.forget_terminal()
            return len(exp)

    def _next(self, a: Assignment, now: float, **changes) -> Assignment:
        d = a.to_dict()
        d.update(changes)
        d["version"] = a.version + 1
        d["updated_at"] = now
        return Assignment.from_dict(d)

    def _commit(self, assigns: list[Assignment]) -> None:
        """Persist first; memory changes only if the write succeeded."""
        self.storage.save_many(assigns)
        self.ledger.apply(assigns)

    def _snap_request(self, snap: ForecastSnapshot, req: RouteRequest):
        nc = self.cfg.network
        dest_ok = (self.net.indeg > 0) & snap.ok.any(1)
        o = self.net.snap(req.origin, self.static_origin_ok, nc.max_snap_m, nc.snap_tie_m)
        d = self.net.snap(req.destination, dest_ok, nc.max_snap_m, nc.snap_tie_m)
        return o, d

    def _prepare(self, snap: ForecastSnapshot, req: RouteRequest, origins=None, dests=None,
                 exclude: str | None = None) -> RequestCandidates | dict:
        if req.depart_at < snap.issued_at:
            return self._unsupported(req, "departure_before_forecast_issue", snap)
        if req.depart_at >= snap.horizon_end:
            return self._unsupported(req, "departure_beyond_forecast_horizon", snap)
        if origins is None or dests is None:
            o, d = self._snap_request(snap, req)
            if not o:
                return self._unsupported(req, "origin_not_on_supported_road", snap)
            if not d:
                return self._unsupported(req, "destination_not_on_supported_road", snap)
            origins, dests = origins or o, dests or d
        cs = cand_mod.generate(self.net, snap, origins, dests, req.depart_at, self.cfg.candidates)
        if not cs.candidates:
            reason = cs.diagnostics.get("outcome", "no_feasible_route")
            if cs.diagnostics.get("dropped", {}).get("infeasible:beyond_horizon") and reason == "no_feasible_route":
                reason = "route_beyond_forecast_horizon"
            out = self._unsupported(req, reason, snap)
            out["candidate_diagnostics"] = cs.diagnostics
            return out
        for c in cs.candidates:
            c.cells = self.ledger.cells_of_entries(c.timed.entries)
        return RequestCandidates(request=req, candidates=cs.candidates, mask=[True] * len(cs.candidates),
                                 fastest_eta_s=cs.fastest_eta_s, exclude_assignment=exclude,
                                 forecast_version=snap.version)

    def _context(self, items: list[RequestCandidates], snap: ForecastSnapshot, exclude: str | None = None):
        now = self.clock()
        b0 = int(now // self.ledger.bin_s)
        b1 = b0 + int(3600 // self.ledger.bin_s)
        future = sum(v for (r, b), v in self.ledger.load.items() if b0 <= b < b1)
        return SelectionContext(items=items, base_load=self.ledger.getter(exclude), cell_coef=self.score.coef,
                                lam=self.cfg.score.lam, forecast_version=snap.version,
                                ledger_version=self.ledger.version, deadline_ms=self.cfg.batch.solve_ms,
                                seed=self.cfg.seed, tie_s=self.cfg.score.tie_s, now=now, snapshot=snap, net=self.net,
                                ledger_live=len(self.ledger.assignments), ledger_future_load=float(future),
                                score_budget=self.score.budget)

    def _validate(self, ctx: SelectionContext, res: SelectionResult) -> str | None:
        for it in ctx.items:
            rid = it.request.request_id
            k = res.choices.get(rid)
            if not valid_indices(it):
                continue
            if k is None:
                return f"no choice for {rid}"
            if not (0 <= k < len(it.candidates)) or not it.mask[k]:
                return f"invalid candidate index {k} for {rid}"
            c = it.candidates[k]
            bound = it.fastest_eta_s + min(self.cfg.candidates.detour_abs_s, self.cfg.candidates.detour_rel * it.fastest_eta_s)
            if c.eta_s > bound + 1e-6:
                return f"detour bound violated for {rid}"
        if set(res.choices) - {it.request.request_id for it in ctx.items}:
            return "choices for unknown requests"
        return None

    def _select(self, ctx: SelectionContext, name: str | None) -> tuple[SelectionResult, str | None]:
        sel = self._selector(name)
        fallback = None
        try:
            res = sel.select(ctx)
            err = self._validate(ctx, res)
            if err:
                fallback = f"invalid_selection: {err}"
            elif sel.name == "batch" and res.runtime_ms > 4 * max(self.cfg.batch.solve_ms, 50):
                fallback = f"timeout: {res.runtime_ms:.0f} ms"
        except SelectorUnavailable as e:
            fallback = f"unavailable: {e}"
        except Exception as e:                            # a crashing policy must not take the service down
            fallback = f"error: {type(e).__name__}: {e}"
        if fallback:
            if self.strict:
                raise SelectorFailed(f"{sel.name}: {fallback}")
            res = self._selector("heuristic").select(ctx)
        return res, fallback

    # ---- public prepare / select / commit seam (used by recommend_batch and by the RL environment) -------------------
    def prepare_request(self, req: RouteRequest, origins=None, dests=None, exclude: str | None = None):
        """Candidates for one request under the current snapshot, or an `unsupported` outcome dict."""
        status, snap = self.store.status(self.clock())
        if status != "ok":
            return self._unsupported(req, f"forecast_{status}", snap)
        return self._prepare(snap, req, origins, dests, exclude)

    def selection_context(self, items: list[RequestCandidates], exclude: str | None = None) -> SelectionContext:
        return self._context(items, self.store.current, exclude)

    def commit_selection(self, items: list[RequestCandidates], res: SelectionResult, fallback: str | None = None,
                         accept: bool = False) -> list[Assignment]:
        """Validate a proposal (from any selector or an RL action) and reserve it: persist, then apply. With
        accept=True the reservation is created directly as accepted (a simulated vehicle that follows it at once).
        Raises Conflict if the proposal is invalid or the forecast changed since the candidates were timed."""
        with self.lock:
            snap = self.store.current
            if any(it.forecast_version != snap.version for it in items):
                raise Conflict("forecast_changed_since_candidates")
            ctx = self._context(items, snap)
            err = self._validate(ctx, res)
            if err:
                raise Conflict(f"invalid_selection: {err}", status=400)
            now = self.clock()
            made = []
            for it in items:
                k = res.choices.get(it.request.request_id)
                if k is None:
                    continue
                a = self._new_assignment(it, k, snap, res, fallback)
                if accept:
                    a.status = "accepted"
                    a.expires_at = max(a.depart_at, now) + self.cfg.ledger.accepted_grace_s
                made.append(a)
            self._commit(made)
            return made

    # ---- recommendations ---------------------------------------------------------------------------------------------
    def recommend(self, req: RouteRequest, selector: str | None = None) -> dict:
        return self.recommend_batch([req], selector)[0]

    def recommend_batch(self, reqs: list[RouteRequest], selector: str | None = None, batch_wait_ms: float = 0.0) -> list[dict]:
        t_start = time.perf_counter()
        now = self.clock()
        self.sweep(now)
        out: dict[int, dict] = {}
        status, snap = self.store.status(now)
        if status != "ok":
            return [self._unsupported(r, f"forecast_{status}", snap) for r in reqs]
        todo: list[tuple[int, RouteRequest]] = []
        seen_ids: dict[str, int] = {}
        for n, r in enumerate(reqs):
            prior = self._existing(r.request_id)
            if prior is not None:
                out[n] = self._assignment_response(prior, duplicate=True)
            elif r.request_id in seen_ids:
                out[n] = {"duplicate_of_index": seen_ids[r.request_id]}
            else:
                seen_ids[r.request_id] = n
                todo.append((n, r))
        for attempt in range(2):
            prepared = {n: self._prepare(snap, r) for n, r in todo}
            with self.lock:
                if self.store.current is not snap and attempt == 0:
                    snap = self.store.current                  # forecast swapped while generating: redo once
                    continue
                self._decide(prepared, snap, selector, out, t_start, batch_wait_ms)
                break
        for n, r in enumerate(reqs):
            if "duplicate_of_index" in out.get(n, {}):
                out[n] = dict(out[out[n]["duplicate_of_index"]], duplicate=True)
        return [out[n] for n in range(len(reqs))]

    def _decide(self, prepared, snap, selector, out, t_start, batch_wait_ms) -> None:
        items = {n: p for n, p in prepared.items() if isinstance(p, RequestCandidates)}
        for n, p in prepared.items():
            if not isinstance(p, RequestCandidates):
                out[n] = p
        # previews are selected one by one and never influence each other or the ledger
        groups = [[n for n in items if items[n].request.reserve]] + [[n] for n in items if not items[n].request.reserve]
        for g in groups:
            if not g:
                continue
            ctx = self._context([items[n] for n in g], snap)
            res, fallback = self._select(ctx, selector)
            new = []
            for n in g:
                it = items[n]
                k = res.choices.get(it.request.request_id)
                if it.request.reserve:
                    new.append((n, self._new_assignment(it, k, snap, res, fallback)))
            try:
                if new:
                    self._commit([a for _, a in new])
            except Exception as e:
                for n in g:
                    out[n] = {"outcome": "error", "reason": f"persistence_failed: {e}", "coordinated": False,
                              "request_id": items[n].request.request_id}
                continue
            made = dict(new)
            latency = (time.perf_counter() - t_start) * 1000 + batch_wait_ms
            for n in g:
                it = items[n]
                out[n] = self._recommendation_response(it, res.choices.get(it.request.request_id), res, fallback, snap,
                                                       made.get(n), latency, len(g), selector or self.selector_name)

    def _new_assignment(self, it: RequestCandidates, k: int, snap: ForecastSnapshot, res: SelectionResult,
                        fallback: str | None) -> Assignment:
        c = it.candidates[k]
        now = self.clock()
        return Assignment(
            assignment_id=uuid.uuid4().hex[:16], request_id=it.request.request_id, version=1, status="provisional",
            created_at=now, updated_at=now, expires_at=now + self.cfg.ledger.provisional_ttl_s,
            depart_at=it.request.depart_at, origin=list(it.request.origin), destination=list(it.request.destination),
            candidate_id=c.candidate_id, route=c.road_ids, schedule=self._schedule(c.timed), progress_idx=0,
            origin_fraction=c.origin_fraction, dest_fraction=c.dest_fraction, eta_s=c.eta_s,
            fastest_eta_s=it.fastest_eta_s, forecast_version=snap.version, network_version=self.net.version,
            selector=res.policy, fallback_reason=fallback,
            alternatives={x.candidate_id: {"route": x.road_ids, "origin_fraction": x.origin_fraction,
                                           "dest_fraction": x.dest_fraction} for x in it.candidates},
            flags=list(c.timed.flags), user_id=it.request.user_id)

    def _schedule(self, tr) -> list:
        return [[str(self.net.ids[e.road]), e.entry, e.exit, e.f0, e.f1] for e in tr.entries]

    def _existing(self, request_id: str) -> Assignment | None:
        aid = self.ledger.by_request.get(request_id)
        if aid:
            return self.ledger.assignments[aid]
        return self.storage.by_request(request_id)

    def _get(self, aid: str) -> Assignment:
        a = self.ledger.assignments.get(aid) or self.storage.get(aid)
        if a is None:
            raise Conflict("unknown_assignment", status=404)
        return a

    def _check_version(self, a: Assignment, expected: int | None) -> None:
        if expected is not None and int(expected) != a.version:
            raise Conflict("version_conflict", a)

    def _retime(self, snap: ForecastSnapshot, route: list, f0: float, g1: float, depart: float):
        return evaluate(self.net, snap, [self.net.pos[r] for r in route], f0, g1, depart)

    # ---- lifecycle ---------------------------------------------------------------------------------------------------
    def get(self, aid: str) -> dict:
        return self._assignment_response(self._get(aid))

    def accept(self, aid: str, expected_version: int | None = None, candidate_id: str | None = None) -> dict:
        now = self.clock()
        self.sweep(now)
        with self.lock:
            a = self._get(aid)
            cid = candidate_id or a.candidate_id
            if a.status == "accepted" and a.candidate_id == cid and expected_version in (None, a.version - 1):
                return self._assignment_response(a, duplicate=True)
            self._check_version(a, expected_version)
            if a.status != "provisional":
                raise Conflict(f"cannot_accept_{a.status}", a)
            if cid not in a.alternatives:
                raise Conflict("unknown_candidate: only a displayed alternative can be accepted", a, 400)
            status, snap = self.store.status(now)
            if status != "ok":
                raise Conflict(f"forecast_{status}", a, 503)
            depart = max(a.depart_at, now)
            timed = {}
            for k, alt in a.alternatives.items():
                try:
                    timed[k] = self._retime(snap, alt["route"], alt["origin_fraction"], alt["dest_fraction"], depart)
                except Infeasible:
                    pass
            if cid not in timed:
                raise Conflict("candidate_no_longer_feasible", a)
            fastest = min(t.eta_s for t in timed.values())
            bound = fastest + min(self.cfg.candidates.detour_abs_s, self.cfg.candidates.detour_rel * fastest)
            if timed[cid].eta_s > bound + 1e-6:
                raise Conflict("candidate_exceeds_detour_bound_now", a)
            alt = a.alternatives[cid]
            b = self._next(a, now, status="accepted", candidate_id=cid, route=alt["route"],
                           origin_fraction=alt["origin_fraction"], dest_fraction=alt["dest_fraction"],
                           schedule=self._schedule(timed[cid]), eta_s=timed[cid].eta_s, fastest_eta_s=fastest,
                           depart_at=depart, forecast_version=snap.version, flags=list(timed[cid].flags),
                           expires_at=depart + self.cfg.ledger.accepted_grace_s)
            self._commit([b])
            return self._assignment_response(b)

    def progress(self, aid: str, expected_version: int | None, road_segment_id: str, at: float | None = None,
                 fraction: float = 0.0) -> dict:
        now = self.clock()
        at = now if at is None else float(at)
        self.sweep(now)
        with self.lock:
            a = self._get(aid)
            if a.status not in ("accepted", "active"):
                raise Conflict(f"cannot_progress_{a.status}", a)
            try:
                idx = a.route.index(road_segment_id, a.progress_idx)
            except ValueError:
                raise Conflict("off_route: request a reroute", a)
            if a.status == "active" and idx == a.progress_idx and expected_version in (None, a.version - 1):
                return self._assignment_response(a, duplicate=True)
            self._check_version(a, expected_version)
            f0 = max(fraction, a.origin_fraction if idx == 0 else 0.0)
            flags = [f for f in a.flags if f not in ("remaining_route_blocked", "remaining_route_untimed")]
            status, snap = self.store.status(now)
            sched = [list(x) for x in a.schedule]
            try:
                if status != "ok":
                    raise Infeasible("forecast_" + status)
                tr = self._retime(snap, a.route[idx:], f0, a.dest_fraction, at)
                sched[idx:] = self._schedule(tr)
                arrive = tr.arrive
            except Infeasible as e:
                delta = at - sched[idx][1]
                for row in sched[idx:]:
                    row[1] += delta
                    row[2] += delta
                arrive = sched[-1][2]
                flags.append("remaining_route_blocked" if e.reason in ("closure", "not_enterable") else "remaining_route_untimed")
            b = self._next(a, now, status="active", progress_idx=idx, schedule=sched, flags=sorted(set(flags)),
                           expires_at=arrive + self.cfg.ledger.active_grace_s)
            self._commit([b])
            return self._assignment_response(b)

    def reroute(self, aid: str, expected_version: int | None, road_segment_id: str, fraction: float = 0.0,
                selector: str | None = None) -> dict:
        """Replace the remaining route from the vehicle's current road; old remaining load is subtracted and the new
        one added in one commit."""
        now = self.clock()
        self.sweep(now)
        status, snap = self.store.status(now)
        with self.lock:
            a = self._get(aid)
            self._check_version(a, expected_version)
            if a.status not in ("accepted", "active"):
                raise Conflict(f"cannot_reroute_{a.status}", a)
            if status != "ok":
                raise Conflict(f"forecast_{status}", a, 503)
            if road_segment_id not in self.net.pos:
                raise Conflict("unknown_road", a, 400)
            req = RouteRequest(request_id=f"{a.request_id}#reroute{a.version}", origin=tuple(a.origin),
                               destination=tuple(a.destination), depart_at=now, user_id=a.user_id)
            origins = [Snap(self.net.pos[road_segment_id], float(fraction), 0.0, ())]
            dests = [Snap(self.net.pos[a.route[-1]], a.dest_fraction, 0.0, ())]
            it = self._prepare(snap, req, origins, dests, exclude=aid)
            if not isinstance(it, RequestCandidates):
                raise Conflict(f"reroute_failed: {it['reason']}", a)
            ctx = self._context([it], snap, exclude=aid)
            res, fallback = self._select(ctx, selector)
            c = it.candidates[res.choices[req.request_id]]
            b = self._next(a, now, status="active", candidate_id=c.candidate_id, route=c.road_ids,
                           schedule=self._schedule(c.timed), progress_idx=0, origin_fraction=c.origin_fraction,
                           eta_s=c.eta_s, fastest_eta_s=it.fastest_eta_s, forecast_version=snap.version,
                           selector=res.policy, fallback_reason=fallback, depart_at=now, flags=list(c.timed.flags),
                           alternatives={x.candidate_id: {"route": x.road_ids, "origin_fraction": x.origin_fraction,
                                                          "dest_fraction": x.dest_fraction} for x in it.candidates},
                           expires_at=c.timed.arrive + self.cfg.ledger.active_grace_s)
            self._commit([b])
            return self._assignment_response(b)

    def _finish(self, aid: str, expected_version: int | None, status: str) -> dict:
        now = self.clock()
        with self.lock:
            a = self._get(aid)
            if a.status == status:
                return self._assignment_response(a, duplicate=True)
            self._check_version(a, expected_version)
            if a.status not in LIVE:
                raise Conflict(f"already_{a.status}", a)
            b = self._next(a, now, status=status, expires_at=now)
            self._commit([b])
            self.ledger.forget_terminal()
            return self._assignment_response(b)

    def cancel(self, aid: str, expected_version: int | None = None) -> dict:
        return self._finish(aid, expected_version, "cancelled")

    def complete(self, aid: str, expected_version: int | None = None) -> dict:
        return self._finish(aid, expected_version, "completed")

    def refresh_forecast(self, snap_or_path) -> dict:
        """Publish a new snapshot (refused if invalid; the old one keeps serving), then re-time every live
        assignment's REMAINING route from its current position and rebuild contributions once. Routes are not
        switched."""
        now = self.clock()
        with self.lock:
            try:
                snap = self.store.publish(snap_or_path)
            except ForecastInvalid as e:
                return {"published": False, "error": str(e), "serving": self.store.current and self.store.current.version}
            upd, untimed = [], 0
            for a in self.ledger.live():
                i = a.progress_idx
                start = max(now, a.schedule[i][1]) if a.status == "active" else max(now, a.depart_at)
                f0 = a.origin_fraction if i == 0 else 0.0
                flags = [f for f in a.flags if f != "remaining_route_untimed"]
                sched = [list(x) for x in a.schedule]
                try:
                    tr = self._retime(snap, a.route[i:], f0, a.dest_fraction, start)
                    sched[i:] = self._schedule(tr)
                except Infeasible:
                    flags.append("remaining_route_untimed")
                    untimed += 1
                upd.append(self._next(a, now, schedule=sched, forecast_version=snap.version, flags=sorted(set(flags))))
            if upd:
                self._commit(upd)
            return {"published": True, "forecast_version": snap.version, "retimed": len(upd), "untimed": untimed}

    # ---- responses ---------------------------------------------------------------------------------------------------
    def _degradation(self, snap: ForecastSnapshot | None, extra=()) -> list:
        flags = set(extra)
        if snap is not None:
            if snap.fixture:
                flags.add("fixture_forecast")
            if snap.provenance.get("synthetic_training"):
                flags.add("synthetic_trained_forecast")
        return sorted(flags)

    def _unsupported(self, req: RouteRequest, reason: str, snap: ForecastSnapshot | None) -> dict:
        return {"outcome": "unsupported", "reason": reason, "request_id": req.request_id, "coordinated": False,
                "note": "no coordinated route; any provider fallback must be labeled uncoordinated",
                "forecast": snap.summary() if snap else None, "degradation": self._degradation(snap)}

    def geometry(self, route_ids: list, f0: float, g1: float) -> dict:
        coords: list = []
        last = len(route_ids) - 1
        for n, r in enumerate(route_ids):
            a = f0 if n == 0 else 0.0
            b = g1 if n == last else 1.0
            for p in self.net.subline(self.net.pos[r], a, max(a, b)):
                if not coords or coords[-1] != p:
                    coords.append(p)
        return {"type": "LineString", "coordinates": coords, "coordinate_order": "lon,lat"}

    def _route_view(self, c: Candidate, fastest: float, geometry: bool = True) -> dict:
        v = {"candidate_id": c.candidate_id, "forecast_eta_sec": round(c.eta_s, 1),
             "extra_travel_sec": round(c.eta_s - fastest, 1), "distance_m": round(c.timed.distance_m, 1),
             "depart_at": iso(c.timed.depart), "arrive_at": iso(c.timed.arrive), "road_segment_ids": c.road_ids,
             "flags": c.timed.flags}
        if geometry:
            v["geometry"] = self.geometry(c.road_ids, c.origin_fraction, c.dest_fraction)
        return v

    def _recommendation_response(self, it: RequestCandidates, k: int, res: SelectionResult, fallback, snap,
                                 a: Assignment | None, latency_ms: float, batch_size: int,
                                 requested: str | None = None) -> dict:
        rid = it.request.request_id
        c = it.candidates[k]
        fastest_c = min(it.candidates, key=lambda x: (x.eta_s, x.candidate_id))
        return {
            "outcome": "recommendation" if a else "preview", "request_id": rid, "coordinated": True,
            "assignment": ({"assignment_id": a.assignment_id, "version": a.version, "status": a.status,
                            "expires_at": iso(a.expires_at)} if a else None),
            "recommended": self._route_view(c, it.fastest_eta_s),
            "fastest_candidate": {"candidate_id": fastest_c.candidate_id,
                                  "forecast_eta_sec": round(fastest_c.eta_s, 1)},
            "is_fastest": c.candidate_id == fastest_c.candidate_id,
            "alternatives": [self._route_view(x, it.fastest_eta_s) for x in it.candidates if x is not c],
            "reasons": res.reasons.get(rid, []),
            "selector": {"name": res.policy, "version": res.policy_version, "requested": requested or self.selector_name,
                         "fallback_reason": fallback, "status": res.status},
            "forecast": snap.summary(), "network_version": self.net.version,
            "degradation": self._degradation(snap, c.timed.flags),
            # selection internals: NOT predicted delay, NOT measured savings
            "allocation_diagnostics": {"selection_scores": res.diagnostics.get(rid, {}), "lambda": self.cfg.score.lam,
                                       "ledger_version": self.ledger.version, "batch_size": batch_size,
                                       "selector_runtime_ms": round(res.runtime_ms, 2),
                                       "solver": res.solver or None},
            "latency_ms": round(latency_ms, 2),
        }

    def _assignment_response(self, a: Assignment, duplicate: bool = False) -> dict:
        snap = self.store.current
        return {"outcome": "assignment", "duplicate": duplicate, "coordinated": True,
                "assignment": {"assignment_id": a.assignment_id, "version": a.version, "status": a.status,
                               "expires_at": iso(a.expires_at), "request_id": a.request_id},
                "route": {"candidate_id": a.candidate_id, "road_segment_ids": a.route,
                          "remaining_from_index": a.progress_idx,
                          "geometry": self.geometry(a.route, a.origin_fraction, a.dest_fraction),
                          "forecast_eta_sec": round(a.eta_s, 1), "fastest_candidate_eta_sec": round(a.fastest_eta_s, 1),
                          "extra_travel_sec": round(a.eta_s - a.fastest_eta_s, 1),
                          "depart_at": iso(a.depart_at), "planned_arrival": iso(a.schedule[-1][2])},
                "selector": {"name": a.selector, "fallback_reason": a.fallback_reason},
                "forecast_version": a.forecast_version, "network_version": a.network_version,
                "degradation": self._degradation(snap, a.flags)}

    def health(self) -> dict:
        now = self.clock()
        status, snap = self.store.status(now)
        return {"status": "ok" if status == "ok" else "degraded", "forecast_status": status,
                "forecast": snap.summary() if snap else None,
                "forecast_age_min": round(snap.age_min(now), 2) if snap else None,
                "last_forecast_error": self.store.last_error, "network_version": self.net.version,
                "selector": self.selector_name, "ledger_version": self.ledger.version,
                "live_assignments": len(self.ledger.live()), "participating_load_total": round(self.ledger.total_load(), 3),
                "recovered_at_start": self.recovered, "now": iso(now)}
