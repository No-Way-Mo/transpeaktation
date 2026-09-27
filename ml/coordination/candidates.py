"""Up to K legal candidate routes per request, generated identically for every selector.

Procedure (deterministic, bounded; an APPROXIMATE candidate set, not a proof of the K best time-dependent routes):
1. Fixed nonnegative weights per search = forecast travel time of one representative interval (the departure
   interval first, then the next ones). Roads not enterable in that interval, or under a full closure for all of
   it, are removed from that search; the exact closure/availability check happens later in timing.evaluate.
2. Search 1 is the unpenalized shortest path on the departure interval and is always kept if it times feasibly.
3. Further searches use the other representative intervals, then overlap penalties
   w * (1 + overlap_penalty * times the road was used by earlier candidates), until K distinct routes or the search
   budget (max_searches) is exhausted.
4. Each path is timed with timing.evaluate; infeasible paths, loops and near-duplicates are dropped with counted
   reasons. Detour bound: ETA <= fastest + min(detour_abs_s, detour_rel * fastest), relative to the fastest
   candidate FOUND, not a global optimum.

Dijkstra runs on scipy's C implementation over a virtual source/sink graph. Arc u->v costs u's travel time;
source -> successors of each origin road cost the origin's remaining part; destination road -> sink costs the
partial destination part. A same-road trip (destination ahead of origin on one road) is a direct candidate.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

from .config import CandidateCfg
from .forecast_store import ForecastSnapshot
from .network import RoadNetwork, Snap
from .schemas import Candidate, TimedRoute, path_hash
from .timing import Infeasible, evaluate, overlap_share


@dataclass
class CandidateSet:
    candidates: list                     # feasible, detour-filtered, ordered by (ETA, path hash)
    fastest_eta_s: float | None
    diagnostics: dict = field(default_factory=dict)


def _search(net: RoadNetwork, w: np.ndarray, origins: list[Snap], dests: list[Snap], limit: float,
            min_w: float) -> list | None:
    """One fixed-weight shortest path. w = per-road traversal seconds, inf = unusable. Returns road indices."""
    N = net.n
    S, T = N, N + 1
    fin = np.isfinite(w)
    m = fin[net.src] & fin[net.dst]
    rows = [net.src[m]]
    cols = [net.dst[m]]
    data = [np.maximum(w[net.src[m]], min_w)]
    s_best: dict[int, tuple[float, int]] = {}
    for o in origins:
        wo = w[o.road] if fin[o.road] else net.ff_tt_s[o.road]
        c = max((1.0 - o.fraction) * wo, min_w)
        for v in net.succ(o.road):
            if fin[v] and (v not in s_best or c < s_best[v][0]):
                s_best[int(v)] = (c, o.road)
    if not s_best:
        return None
    rows.append(np.full(len(s_best), S)); cols.append(np.fromiter(s_best.keys(), np.int64, len(s_best)))
    data.append(np.array([v[0] for v in s_best.values()]))
    d_frac: dict[int, float] = {}
    for d in dests:
        if fin[d.road]:
            d_frac[d.road] = d.fraction
    if not d_frac:
        return None
    rows.append(np.fromiter(d_frac.keys(), np.int64, len(d_frac))); cols.append(np.full(len(d_frac), T))
    data.append(np.array([max(f * w[r], min_w) for r, f in d_frac.items()]))
    G = csr_matrix((np.concatenate(data), (np.concatenate(rows), np.concatenate(cols))), shape=(N + 2, N + 2))
    dist, pred = dijkstra(G, directed=True, indices=S, return_predecessors=True, limit=limit)
    if not np.isfinite(dist[T]):
        return None
    path = []
    j = pred[T]
    while j != S and j >= 0:
        path.append(int(j))
        j = pred[j]
    path.reverse()
    if not path:
        return None
    return [s_best[path[0]][1]] + path


def _has_loop(path: list) -> bool:
    if len(set(path)) == len(path):
        return False
    # only allowed repeat: origin road re-entered as destination (destination behind the origin on one road)
    return not (path[0] == path[-1] and len(set(path)) == len(path) - 1)


def generate(net: RoadNetwork, snap: ForecastSnapshot, origins: list[Snap], dests: list[Snap], depart: float,
             cfg: CandidateCfg) -> CandidateSet:
    t0 = time.perf_counter()
    diag = {"searches": 0, "search_ms": 0.0, "raw_paths": 0, "dropped": {}}

    def drop(reason):
        diag["dropped"][reason] = diag["dropped"].get(reason, 0) + 1

    k0 = snap.bucket(depart)
    if k0 < 0 or k0 >= snap.H:
        return CandidateSet([], None, {**diag, "outcome": "beyond_horizon"})
    intervals = list(dict.fromkeys(min(k0 + j, snap.H - 1) for j in range(3)))
    limit = float(snap.horizon_end - depart) * 1.5
    found: list[tuple[list, TimedRoute, str, Snap, Snap]] = []
    seen: set[tuple] = set()

    def consider(path, source):
        diag["raw_paths"] += 1
        key = tuple(path)
        if key in seen:
            drop("duplicate")
            return
        seen.add(key)
        if _has_loop(path):
            drop("loop")
            return
        o = next(s for s in origins if s.road == path[0])
        d = next((s for s in dests if s.road == path[-1]), None)
        if d is None:
            drop("no_destination_match")
            return
        try:
            tr = evaluate(net, snap, path, o.fraction, d.fraction, depart)
        except Infeasible as e:
            drop(f"infeasible:{e.reason}")
            return
        found.append((path, tr, source, o, d))

    # same-road trip: destination ahead of the origin on one road
    for o in origins:
        for d in dests:
            if o.road == d.road and d.fraction >= o.fraction:
                consider([o.road], "same_road")

    usage = np.zeros(net.n)
    base_w = {}
    for k in intervals:
        w = np.where(snap.ok[:, k], snap.tt[:, k], np.inf)
        t_lo, t_hi = snap.issued_at + k * snap.bucket_s, snap.issued_at + (k + 1) * snap.bucket_s
        for i, cl in snap.closures.items():
            if any(kind not in ("partial", "lane") and b <= t_lo and e >= t_hi for b, e, kind in cl):
                w[i] = np.inf
        base_w[k] = w

    plan = [(k, 0.0) for k in intervals] + [(k0, cfg.overlap_penalty)] * max(0, cfg.max_searches - len(intervals))
    for k, pen in plan:
        if len(found) >= cfg.k * 2 or diag["searches"] >= cfg.max_searches:
            break
        w = base_w[k] * (1.0 + pen * usage) if pen > 0 else base_w[k]
        ts = time.perf_counter()
        path = _search(net, w, origins, dests, limit, cfg.min_weight_s)
        diag["searches"] += 1
        diag["search_ms"] += (time.perf_counter() - ts) * 1000
        if path is None:
            if pen == 0 and k == k0:
                diag["unpenalized_search_failed"] = True
            continue
        consider(path, f"interval_{k}" + ("_penalized" if pen else ""))
        usage[path] += 1

    if not found:
        return CandidateSet([], None, {**diag, "outcome": "no_feasible_route",
                                       "runtime_ms": (time.perf_counter() - t0) * 1000})
    fastest = min(f[1].eta_s for f in found)
    bound = fastest + min(cfg.detour_abs_s, cfg.detour_rel * fastest)
    found.sort(key=lambda f: (f[1].eta_s, path_hash([str(net.ids[r]) for r in f[0]])))
    kept: list = []
    for path, tr, source, o, d in found:
        if tr.eta_s > bound + 1e-9:
            drop("detour_bound")
            continue
        if kept and overlap_share(tr, kept[0][1]) > cfg.max_overlap and overlap_share(kept[0][1], tr) > cfg.max_overlap:
            drop("near_duplicate")
            continue
        if len(kept) >= cfg.k:
            drop("over_k")
            continue
        kept.append((path, tr, source, o, d))
    cands = []
    for path, tr, source, o, d in kept:
        ids = [str(net.ids[r]) for r in path]
        c = Candidate(candidate_id=path_hash(ids), road_ids=ids, timed=tr, origin_fraction=o.fraction,
                      dest_fraction=d.fraction, source=source)
        cands.append(c)
    for c in cands:
        others = [overlap_share(c.timed, x.timed) for x in cands if x is not c]
        c.features = {"eta_s": c.eta_s, "distance_m": c.timed.distance_m, "extra_travel_s": c.eta_s - fastest,
                      "overlap_with_fastest": overlap_share(c.timed, cands[0].timed),
                      "max_overlap_other_candidates": max(others) if others else 0.0,
                      "class_exposure_s": c.timed.class_exposure_s, "roads": len(c.road_ids)}
    diag.update({"outcome": "ok", "feasible_found": len(found), "kept": len(cands),
                 "runtime_ms": (time.perf_counter() - t0) * 1000, "detour_bound_s": bound - fastest})
    return CandidateSet(cands, fastest, diag)
