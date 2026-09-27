"""Matched selector comparison (RL_ROUTING_RESEARCH_AND_PLAN.md §7).

Suites
* static     one snapshot per development scenario: every policy chooses for the same prepared requests (no
             simulation after the choice). Compares latency, masks, non-fastest share and the shared allocation
             score only. No traffic outcome.
* profile    one development scenario x one simulation seed x every policy, dynamic (timing breakdown).
* screening  development scenarios (`benchmark.screening_split`) x `benchmark.seeds` x every policy, dynamic.
* heldout    held-out scenarios (`benchmark.heldout_split`) x seeds x every policy, dynamic. Freeze choices first.

A dynamic run is one RouteChoiceEnv episode driven by a selector instead of an agent: identical exogenous demand,
participants, compliance draws, simulation seed and verified warm state (prebuilt once per scenario x seed before
any policy runs), but each policy's own evolving traffic and forecasts. Requests are revealed at their scheduled
departure. The batch policy decides the requests that arrived within `batch_window_s` jointly; they depart when the
batch is decided and that wait is added to realized vehicle time. RL policies use their checkpoints through the RL
selector (strict: an unavailable checkpoint is reported as unavailable, never replaced by another policy).

Metrics come from SUMO (tripinfo + the vehicle-time accountant + congestion exposure), not from selection scores.

Policy variants (LOAD_BALANCING_BACKTEST_PLAN.md §6): `<policy>@key=value[@key=value]` with
* `lam`   score.lam (the heuristic/batch concentration weight; lam=0 must reproduce independent routing),
* `w`     decision window in seconds (default: `benchmark.batch_window_s` for `batch`, 0 = immediate otherwise);
          `heuristic@w=60` is the equal-timing control for `batch`,
* `rep`   label only (repeatability: the same policy twice on the same block).
Every run is filed under an experiment id (a digest of the resolved config, code, policies, scenarios and seeds),
so reruns never overwrite a different configuration; with `resume` only missing or failed tasks of the identical
experiment are run again. A frozen manifest (config, code, SUMO, input digests, participants) is written first.
"""
from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import math
import os
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

import numpy as np

from ..config import Config, from_dict
from ..schemas import SelectionResult
from ..selectors import SelectorUnavailable, make
from ..selectors.base import exact_joint_score, valid_indices
from ..selectors.rl import RL

DYNAMIC = ("profile", "screening", "heldout")
SUITES = ("static",) + DYNAMIC


# ---------------------------------------------------------------- scenario choice

def suite_split(cfg: Config, suite: str) -> str:
    return cfg.benchmark.heldout_split if suite == "heldout" else cfg.benchmark.screening_split


def validate_scenarios(cfg: Config, suite: str, ids: list[str]) -> None:
    """Explicit scenario lists must belong to the suite's split (no test scenarios in screening, no train/val
    scenarios in held-out evaluation) and pass the batch quality gate."""
    from ..rl import scenario
    want = suite_split(cfg, suite)
    specs = {s.scenario_id: s for s in scenario.load(cfg, None, list(ids))}
    bad = [i for i in ids if i not in specs]
    if bad:
        raise SystemExit(f"scenarios not available (missing, flagged or not quality-gated): {bad}")
    wrong = [f"{i} ({specs[i].split})" for i in ids if specs[i].split != want]
    if wrong:
        raise SystemExit(f"suite {suite} uses split {want!r}; refusing scenarios from other splits: {wrong}")


def choose_scenarios(cfg: Config, suite: str, only: list | None = None) -> list[str]:
    """Deterministic: event runs of the suite's split, rotating arrival / departure / full windows, one run per
    scenario family before any family is reused (runs of one family differ only in their demand seed)."""
    from ..rl import scenario
    if only:
        validate_scenarios(cfg, suite, only)
        return list(only)
    b = cfg.benchmark
    split = b.heldout_split if suite == "heldout" else b.screening_split
    n = {"heldout": b.heldout_scenarios, "profile": 1}.get(suite, b.screening_scenarios)
    bdir = cfg.path(cfg.env.sim_root) / "batches" / cfg.env.batch
    sc = json.loads((bdir / "scenarios.json").read_text())
    fams = {f["family_id"]: f for f in sc["families"]}
    ids = {s.scenario_id for s in scenario.load(cfg, split)}
    by_window: dict = {}
    for r in sorted(sc["runs"], key=lambda r: r["run_id"]):
        if r["run_id"] not in ids or (b.event_runs_only and not r["with_event"]):
            continue
        by_window.setdefault(fams[r["family_id"]]["window"], []).append(r)
    for w, rs in by_window.items():                  # first run of every family, then the families' second runs, ...
        rank, seen = [], {}
        for r in rs:
            seen[r["family_id"]] = seen.get(r["family_id"], -1) + 1
            rank.append((seen[r["family_id"]], r["run_id"]))
        by_window[w] = [rid for _, rid in sorted(rank)]
    out, i = [], 0
    order = [w for w in ("arrival", "departure", "full") if w in by_window]
    while len(out) < n and any(by_window.values()):
        w = order[i % len(order)]
        if by_window[w]:
            out.append(by_window[w].pop(0))
        i += 1
    return out


# ---------------------------------------------------------------- policies

POLICY_KEYS = ("lam", "w", "rep")


def parse_policy(spec: str) -> tuple[str, dict]:
    """'heuristic@lam=120@w=60' -> ('heuristic', {'lam': 120.0, 'w': 60.0})."""
    base, *parts = spec.split("@")
    over = {}
    for p in parts:
        k, _, v = p.partition("=")
        if k not in POLICY_KEYS or not v:
            raise SystemExit(f"bad policy variant {spec!r}: use <policy>@key=value with key in {POLICY_KEYS}")
        over[k] = v if k == "rep" else float(v)
    return base, over


def policy_setup(cfg: Config, spec: str) -> tuple[Config, str, float]:
    """(config with the variant's overrides, base policy name, decision window in seconds)."""
    base, over = parse_policy(spec)
    c = copy.deepcopy(cfg)
    if "lam" in over:
        c.score.lam = over["lam"]
    window = over.get("w", cfg.benchmark.batch_window_s if base == "batch" else 0.0)
    return c, base, float(window)


def chooser(cfg: Config, policy: str):
    """ctx -> SelectionResult. RL policies are strict: SelectorUnavailable propagates."""
    policy = parse_policy(policy)[0]
    if policy.startswith("rl_"):
        ck = cfg.benchmark.checkpoints.get(policy)
        if not ck:
            raise SelectorUnavailable(f"no checkpoint configured for {policy}")
        if not (cfg.path(ck) / "meta.json").exists():   # fail before simulating anything
            raise SelectorUnavailable(f"rl_not_trained: no checkpoint at {cfg.path(ck)}")
        sel = RL(cfg, checkpoint=ck)
    else:
        sel = make(policy, cfg)
    return sel.select


def checkpoint_status(cfg: Config) -> dict:
    out = {}
    for p in cfg.benchmark.policies:
        p = parse_policy(p)[0]
        if p.startswith("rl_"):
            ck = cfg.benchmark.checkpoints.get(p, "")
            out[p] = {"checkpoint": ck, "exists": bool(ck) and (cfg.path(ck) / "meta.json").exists()}
    return out


# ---------------------------------------------------------------- dynamic episode

def _env_cls():
    from ..rl.sumo_env import RouteChoiceEnv

    class BenchEnv(RouteChoiceEnv):
        def warm(self, scenario_id: str, seed_off: int) -> dict:
            """History period only: builds (or verifies) the shared warm state."""
            self._close()
            spec = next(s for s in self.specs if s.scenario_id == scenario_id)
            self._begin(spec, int(seed_off))
            self.sim.close()
            return {"scenario": scenario_id, "seed_offset": seed_off, "used_warm_state": self.used_warm_state,
                    "startup_s": round(self.wall["startup_s"], 1)}

        def run_policy(self, scenario_id: str, seed_off: int, choose, window_s: float = 0.0) -> dict:
            self._close()
            spec = next(s for s in self.specs if s.scenario_id == scenario_id)
            self._begin(spec, int(seed_off))
            self.episode += 1
            step = float(self.cfg.env.step_s)
            b = {"calls": 0, "decided": 0, "non_fastest": 0, "call_ms": [], "batch_sizes": [], "delays_s": [],
                 "selector_failures": 0, "unchosen": 0, "extra_travel_s": []}
            while self.queue:
                first = self.queue[0]
                if window_s > 0:
                    t_dec = math.ceil(first.depart + window_s) - step
                    group = [t for t in self.queue if t.depart < first.depart + window_s]
                else:
                    t_dec = math.ceil(first.depart) - step
                    group = [first]
                self._run_until(max(self.t, t_dec))
                del self.queue[:len(group)]
                multi = []
                for trip in group:
                    if window_s > 0:
                        dep = max(trip.depart, self.t + step)
                        delay = dep - trip.depart
                        if delay > 0:            # waited for the batch: realized vehicle time, not a free delay
                            self.acct.total_s += delay
                            self.acct._since += delay
                        b["delays_s"].append(delay)
                        trip = dataclasses.replace(trip, depart=dep)
                    req, o, d = self._request(trip)
                    item = self.coord.prepare_request(req, o, d)
                    if isinstance(item, dict):
                        reason = item.get("reason", "unsupported")
                        self.stats["unsupported_fallback"] += 1
                        self.stats["unsupported_reasons"][reason] = self.stats["unsupported_reasons"].get(reason, 0) + 1
                        self._add_fallback(trip)
                        continue
                    valid = [j for j, ok in enumerate(item.mask) if ok and j < self.K]
                    if len(valid) == 1:
                        res = SelectionResult(choices={req.request_id: valid[0]}, policy="direct_single_candidate",
                                              policy_version="direct")
                        self._commit_and_apply(trip, item, res, trivial=True)
                        self.stats["trivial"] += 1
                        continue
                    multi.append((trip, item, valid))
                if not multi:
                    continue
                ctx = self.coord.selection_context([it for _, it, _ in multi])
                t0 = time.perf_counter()
                try:
                    res = choose(ctx)
                except SelectorUnavailable:
                    raise
                except Exception as e:           # a crashing selector is a recorded failure; demand is kept
                    b["selector_failures"] += 1
                    self.stats.setdefault("selector_errors", []).append(f"{type(e).__name__}: {e}"[:300])
                    res = SelectionResult(choices={}, policy="failed", policy_version="failed")
                b["call_ms"].append((time.perf_counter() - t0) * 1000)
                b["calls"] += 1
                b["batch_sizes"].append(len(multi))
                for trip, item, valid in multi:
                    rid = item.request.request_id
                    k = res.choices.get(rid)
                    if k is None or k not in valid:
                        b["unchosen"] += 1
                        self._add_fallback(trip)
                        continue
                    one = SelectionResult(choices={rid: k}, policy=res.policy, policy_version=res.policy_version)
                    self._commit_and_apply(trip, item, one, trivial=False)
                    self.stats["decisions"] += 1
                    b["decided"] += 1
                    fastest = min(valid, key=lambda j: (item.candidates[j].eta_s, item.candidates[j].candidate_id))
                    b["non_fastest"] += int(k != fastest)
                    b["extra_travel_s"].append(item.candidates[k].eta_s - item.candidates[fastest].eta_s)
            self._drain()
            s = self._finish()["episode_summary"]
            s["bench"] = _bench_stats(b)
            s["outcomes"] = tripinfo_outcomes(self.edir / "tripinfo.xml", self.acct.P, {t.id for t in self.parts},
                                              self.depart_of)
            (self.edir / "summary.json").write_text(json.dumps(s, indent=1, default=str))
            return s

    return BenchEnv


def _q(x, q):
    return float(np.percentile(x, q)) if len(x) else None


def _bench_stats(b: dict) -> dict:
    return {"selector_calls": b["calls"], "decided": b["decided"], "non_fastest": b["non_fastest"],
            "non_fastest_share": b["non_fastest"] / b["decided"] if b["decided"] else None,
            "selector_failures": b["selector_failures"], "unchosen_fallback": b["unchosen"],
            "call_ms_p50": _q(b["call_ms"], 50), "call_ms_p95": _q(b["call_ms"], 95),
            "batch_size_mean": float(np.mean(b["batch_sizes"])) if b["batch_sizes"] else None,
            "batch_delay_s_mean": float(np.mean(b["delays_s"])) if b["delays_s"] else 0.0,
            "batch_delay_s_p95": _q(b["delays_s"], 95) or 0.0,
            "forecast_extra_travel_s_mean": float(np.mean(b["extra_travel_s"])) if b["extra_travel_s"] else None}


def tripinfo_outcomes(path: Path, in_scope: set, parts: set, depart_of: dict) -> dict:
    """Realized trip outcomes of in-scope vehicles that arrived, split into participants and the rest."""
    rows = {"participants": [], "others": []}
    if path.exists():
        try:
            for _, el in ET.iterparse(path, events=("end",)):
                if el.tag == "tripinfo":
                    vid = el.get("id")
                    if vid in in_scope and el.get("arrival", "-1") not in ("-1", "-1.00"):
                        arr = float(el.get("arrival"))
                        rec = (arr - depart_of.get(vid, float(el.get("depart"))), float(el.get("timeLoss")),
                               float(el.get("routeLength")))
                        rows["participants" if vid in parts else "others"].append(rec)
                el.clear()
        except ET.ParseError:
            pass
    out = {}
    for k, v in rows.items():
        a = np.array(v) if v else np.zeros((0, 3))
        out[k] = {"arrived": len(v),
                  "trip_s_mean": float(a[:, 0].mean()) if len(v) else None,
                  "trip_s_median": _q(a[:, 0], 50), "trip_s_p95": _q(a[:, 0], 95),
                  "time_loss_s_mean": float(a[:, 1].mean()) if len(v) else None,
                  "route_m_mean": float(a[:, 2].mean()) if len(v) else None,
                  "note": "trip time counted from the scheduled departure (includes insertion/batching waits)"}
    return out


# ---------------------------------------------------------------- run quality and identity

def quality(s: dict) -> dict:
    """Strict completeness of one dynamic episode (plan §4C). Teleports are allowed (SUMO time-to-teleport) but
    counted and reported; they are not a failure by themselves."""
    b = s.get("bench") or {}
    checks = {"all_in_scope_arrived": s.get("terminated") is True,
              "no_dropped_trips": not s.get("dropped_trips"),
              "no_invalid_routes": not s.get("invalid_route"),
              "no_route_readback_mismatch": not s.get("route_readback_mismatch"),
              "no_selector_failures": not b.get("selector_failures"),
              "no_unchosen_fallbacks": not b.get("unchosen_fallback"),
              "no_forecast_failures": not s.get("forecast_refresh_failures")}
    return {"complete": all(checks.values()), "failed_checks": [k for k, v in checks.items() if not v]}


def code_identity() -> dict:
    """Digest of the code that produces results (coordination, eventsim, forecast sources). TP_CODE_ID (e.g. a
    bundle digest set by a cloud node) is recorded alongside."""
    from ..config import ML_DIR
    h = hashlib.sha256()
    n = 0
    skip = {"coordination/benchmark/report.py", "coordination/benchmark/backtest.py", "coordination/__main__.py"}
    for pkg in ("coordination", "eventsim", "forecast"):  # simulation/decision code only: report edits keep ids
        for f in sorted((ML_DIR / pkg).rglob("*.py")):
            if f.relative_to(ML_DIR).as_posix() in skip:
                continue
            h.update(f.relative_to(ML_DIR).as_posix().encode())
            h.update(f.read_bytes().replace(b"\r\n", b"\n"))
            n += 1
    return {"sources_sha": h.hexdigest()[:16], "files": n, "tp_code_id": os.environ.get("TP_CODE_ID", "")}


def experiment_id(cfg: Config, suite: str, policies: list, scenarios: list, seeds: list, code: dict) -> str:
    """Digest of everything that can change results. Execution settings (worker count) are excluded, so nodes of
    different sizes and a later report-only run agree on the id."""
    c = cfg.to_dict()
    c["benchmark"] = {k: v for k, v in c["benchmark"].items() if k != "workers"}
    body = json.dumps({"config": c, "suite": suite, "policies": list(policies), "scenarios": list(scenarios),
                       "seeds": list(seeds), "code": code["sources_sha"]}, sort_keys=True, default=str)
    return f"{suite}_{cfg.name}_{hashlib.sha256(body.encode()).hexdigest()[:10]}"


def manifest(cfg: Config, net, suite: str, policies: list, scenarios: list, seeds: list, exp: str, code: dict) -> dict:
    """Frozen before any worker starts: resolved config, code, SUMO, inputs and the exact participant cohorts."""
    from ..network import sha256_file
    from ..rl import scenario
    from ..rl.sumo_env import _digest, sumo_version
    ec = cfg.env
    specs = scenario.load(cfg, None, list(scenarios))
    per = []
    for sp in specs:
        t0 = sp.time["sim_begin_s"] + ec.history_s
        t1 = min(t0 + ec.decision_window_s, sp.time["depart_end_s"])
        parts = scenario.participants(sp, net, t0, t1, ec.participation, ec.max_participants)
        elig = scenario.participants(sp, net, t0, t1, 1.0, 10 ** 9)
        trips = sp.get_trips()
        in_scope = sum(1 for t in trips if t.depart < t1)
        departs = sum(1 for t in trips if t0 <= t.depart < t1)
        per.append({"scenario": sp.scenario_id, "family": sp.family_id, "split": sp.split, "group": sp.group,
                    "trips": len(trips), "in_scope": in_scope, "window_departures": departs, "eligible": len(elig),
                    "participants": len(parts), "participants_sha": _digest(sorted(t.id for t in parts)),
                    "share_of_eligible": len(parts) / max(len(elig), 1),
                    "share_of_window_departures": len(parts) / max(departs, 1),
                    "share_of_in_scope": len(parts) / max(in_scope, 1),
                    "closures_sha256": sha256_file(sp.add_src), "net": sp.net_file.name})
    fc = cfg.path(ec.forecast_checkpoint)
    return {"experiment_id": exp, "suite": suite, "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "policies": {p: dict(zip(("base", "overrides"), parse_policy(p))) for p in policies},
            "scenarios": list(scenarios), "seeds": list(seeds), "config_name": cfg.name, "config_hash": cfg.hash(),
            "config": cfg.to_dict(), "code": code, "sumo_version": sumo_version(),
            "forecast": {"mode": ec.forecast_mode, "checkpoint": ec.forecast_checkpoint,
                         "sha256": sha256_file(fc) if ec.forecast_mode == "model" and fc.exists() else None},
            "rl_checkpoints": checkpoint_status(cfg), "scenario_inputs": scenario.manifest(cfg, specs),
            "cohorts": per,
            "notes": ["participants are nested across participation levels (lowest seeded draws first)",
                      "compliance draws are keyed by (scenario, vehicle), identical for every policy",
                      f"teleports allowed after {ec.time_to_teleport_s} s (counted, reported)"]}


# ---------------------------------------------------------------- workers (one process per task)

_NET: dict = {}


def _setup(cfg_dict: dict, scenario_id: str):
    from ..rl import scenario
    from ..runtime import load_network
    cfg = from_dict(cfg_dict)
    if "net" not in _NET:
        _NET["net"] = load_network(cfg)
    specs = scenario.load(cfg, None, [scenario_id])
    if not specs:
        raise RuntimeError(f"scenario {scenario_id} not available (missing, flagged or not quality-gated)")
    return cfg, _NET["net"], specs


def _peak_mb() -> dict:
    try:
        import resource
        return {"self_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                "children_mb": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024}
    except Exception:                          # not available on Windows
        return {}


def warm_task(cfg_dict: dict, scenario_id: str, seed_off: int, debug_forecast: bool = False) -> dict:
    """The saved state (SUMO + measured history) does not depend on the forecast, so it may be built with the
    labeled persistence stand-in before the trained forecaster exists (`prewarm --debug-forecast`)."""
    if debug_forecast:
        cfg_dict = {**cfg_dict, "env": {**cfg_dict["env"], "forecast_mode": "persistence_debug"}}
    cfg, net, specs = _setup(cfg_dict, scenario_id)
    env = _env_cls()(cfg, net, specs, policy_name="warm", tag="bench_warm", allow_debug_forecast=debug_forecast)
    try:
        return env.warm(scenario_id, seed_off)
    finally:
        env.close()


def task_path(out_dir, exp: str, policy: str, scenario_id: str, seed_off: int) -> Path:
    return Path(out_dir) / exp / "runs" / policy / f"{scenario_id}_s{seed_off}.json"


def dynamic_task(cfg_dict: dict, suite: str, policy: str, scenario_id: str, seed_off: int, out_dir: str,
                 exp: str = "") -> dict:
    t0 = time.time()
    base_cfg, net, specs = _setup(cfg_dict, scenario_id)
    rec = {"experiment_id": exp, "suite": suite, "policy": policy, "scenario": scenario_id, "seed_offset": seed_off}
    try:
        cfg, base, window = policy_setup(base_cfg, policy)
        rec.update(base_policy=base, window_s=window, lam=cfg.score.lam)
        choose = chooser(cfg, policy)
        env = _env_cls()(cfg, net, specs, policy_name=base, tag=f"bench_{exp or suite}_{policy}")
        try:
            s = env.run_policy(scenario_id, seed_off, choose, window)
        finally:
            env.close()
        rec.update(status="ok", summary=s, quality=quality(s))
    except SelectorUnavailable as e:
        rec.update(status="unavailable", error=str(e))
    except Exception as e:
        import traceback
        rec.update(status="failed", error=f"{type(e).__name__}: {e}", trace=traceback.format_exc()[-2000:])
    rec["wall_s"] = round(time.time() - t0, 1)
    rec["peak_mem"] = _peak_mb()
    p = task_path(out_dir, exp, policy, scenario_id, seed_off) if exp else \
        Path(out_dir) / suite / policy / f"{scenario_id}_s{seed_off}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rec, indent=1, default=str))
    return rec


def static_task(cfg_dict: dict, scenario_id: str, policies: list) -> dict:
    """All participants of the decision window prepared on the forecast at the window start (empty ledger), then
    each policy chooses for the same requests in arrival-order chunks. Nothing is committed or simulated."""
    cfg, net, specs = _setup(cfg_dict, scenario_id)
    env = _env_cls()(cfg, net, specs, policy_name="static", tag="bench_static")
    try:
        env._close()
        env._begin(specs[0], 0)
        env.sim.close()
        items = []
        for trip in env.parts:
            req, o, d = env._request(trip)
            it = env.coord.prepare_request(req, o, d)
            if not isinstance(it, dict) and len(valid_indices(it)) > 1:
                items.append(it)
        rows = {"scenario": scenario_id, "participants": len(env.parts), "multi_candidate_requests": len(items),
                "valid_count_hist": np.bincount([len(valid_indices(i)) for i in items], minlength=cfg.candidates.k + 1)
                .tolist(), "policies": {}}
        n = cfg.benchmark.static_chunk
        for p in policies:
            try:
                choose = chooser(cfg, p)
            except SelectorUnavailable as e:
                rows["policies"][p] = {"status": "unavailable", "error": str(e)}
                continue
            ms, choices, eta, pen = [], {}, 0.0, 0.0
            try:
                for i in range(0, len(items), n):
                    ctx = env.coord.selection_context(items[i:i + n])
                    t0 = time.perf_counter()
                    res = choose(ctx)
                    ms.append((time.perf_counter() - t0) * 1000)
                    choices.update(res.choices)
                    sc = exact_joint_score(ctx, res.choices)
                    eta, pen = eta + sc["eta_s"], pen + sc["penalty"]
            except SelectorUnavailable as e:
                rows["policies"][p] = {"status": "unavailable", "error": str(e)}
                continue
            nf = sum(1 for it in items if choices.get(it.request.request_id, 0) != min(
                valid_indices(it), key=lambda j: (it.candidates[j].eta_s, it.candidates[j].candidate_id)))
            rows["policies"][p] = {"status": "ok", "chosen": len(choices), "non_fastest": nf,
                                   "forecast_eta_sum_s": round(eta, 1), "allocation_penalty_sum": round(pen, 6),
                                   "call_ms_p50": _q(ms, 50), "call_ms_p95": _q(ms, 95), "calls": len(ms)}
        return rows
    finally:
        env.close()


def _pool(n: int, cfg: Config | None = None, workers: int | None = None):
    w = workers or (cfg.benchmark.workers if cfg else 0) or os.cpu_count() or 1
    import multiprocessing as mp
    return ProcessPoolExecutor(max_workers=max(1, min(n, w)), mp_context=mp.get_context("spawn"))


@dataclasses.dataclass
class Experiment:
    """One matched comparison: every policy on every scenario x seed under one resolved config."""
    cfg: Config
    suite: str
    policies: list
    scenarios: list
    seeds: list
    exp: str = ""
    code: dict = dataclasses.field(default_factory=dict)


def prepare(cfg: Config, suite: str, policies: list | None = None, scenarios: list | None = None,
            seeds: list | None = None) -> Experiment:
    if suite not in SUITES:
        raise SystemExit(f"unknown suite {suite!r}; choose from {SUITES}")
    policies = list(policies or cfg.benchmark.policies)
    for p in policies:
        parse_policy(p)
    if len(set(policies)) != len(policies):
        raise SystemExit(f"duplicate policies: {policies} (use @rep=<label> for a repeat)")
    scen = choose_scenarios(cfg, suite, scenarios)
    if not scen:
        raise SystemExit(f"no scenarios for suite {suite}")
    if suite == "heldout":
        from ..rl import scenario
        fams = [s.family_id for s in scenario.load(cfg, None, scen)]
        if len(set(fams)) < len(fams):
            print(json.dumps({"warning": "held-out scenarios repeat a family (demand-seed replicates, not "
                                         "independent families)", "families": fams}))
    seeds = list(seeds if seeds is not None else ([0] if suite in ("profile", "static") else cfg.benchmark.seeds))
    code = code_identity()
    return Experiment(cfg, suite, policies, scen, seeds, experiment_id(cfg, suite, policies, scen, seeds, code), code)


def _warm_key(e: Experiment, scenario_id: str, seed: int) -> str:
    """Warm states depend on the environment, not on compliance or the forecaster (built with the labeled
    persistence stand-in; the saved state is taken before any forecast is used)."""
    env = {k: v for k, v in e.cfg.to_dict()["env"].items() if k not in ("compliance", "forecast_mode",
                                                                         "forecast_checkpoint", "forecast_device")}
    return json.dumps([env, scenario_id, seed], sort_keys=True, default=str)


def _failed(exps: list, key: tuple, why: str) -> dict:
    ei, p, s, k = key
    return {"experiment_id": exps[ei].exp, "suite": exps[ei].suite, "policy": p, "scenario": s, "seed_offset": k,
            "status": "failed", "error": why[:500]}


def run_many(exps: list, workers: int | None = None, resume: bool = True, log=print) -> list:
    """Several experiments in one process pool: frozen manifests first, then one verified warm state per distinct
    (warm identity, scenario, seed), then every missing (experiment, policy, scenario, seed) task."""
    from ..rl import scenario
    from ..runtime import load_network
    net = load_network(exps[0].cfg)            # build the network cache once, before workers race for it
    for e in exps:
        if e.suite == "static":
            raise SystemExit("run_many runs dynamic suites; use run() for static")
        d = e.cfg.path(e.cfg.benchmark.out_dir) / e.exp
        d.mkdir(parents=True, exist_ok=True)
        if not (d / "manifest.json").exists():
            m = manifest(e.cfg, net, e.suite, e.policies, e.scenarios, e.seeds, e.exp, e.code)
            (d / "manifest.json").write_text(json.dumps(m, indent=1, default=str))
        log(json.dumps({"experiment": e.exp, "suite": e.suite, "policies": e.policies, "scenarios": e.scenarios,
                        "seeds": e.seeds}))
    done: dict = {}
    todo = []
    for ei, e in enumerate(exps):
        out = e.cfg.path(e.cfg.benchmark.out_dir)
        for s in e.scenarios:
            for k in e.seeds:
                for p in e.policies:
                    f = task_path(out, e.exp, p, s, k)
                    if resume and f.exists():
                        r = json.loads(f.read_text())
                        if r.get("experiment_id") == e.exp and r.get("status") in ("ok", "unavailable"):
                            done[(ei, p, s, k)] = r
                            continue
                    todo.append((ei, p, s, k))
    log(json.dumps({"tasks_total": len(todo) + len(done), "resumed": len(done), "to_run": len(todo)}))
    t0 = time.time()
    warm = {}
    for ei, p, s, k in todo:
        warm.setdefault(_warm_key(exps[ei], s, k), (exps[ei].cfg.to_dict(), s, k))
    nw = workers or exps[0].cfg.benchmark.workers
    if warm:
        with _pool(len(warm), workers=nw) as ex:
            futs = {ex.submit(warm_task, cd, s, k, True): (s, k) for cd, s, k in warm.values()}
            for f in as_completed(futs):
                try:
                    log(json.dumps({"warm": f.result(), "elapsed_s": round(time.time() - t0)}))
                except Exception as err:        # the dynamic tasks rebuild it (and record any real failure)
                    log(json.dumps({"warm_failed": futs[f], "error": str(err)[:300]}))
    size = {}
    for e in exps:
        for sp in scenario.load(e.cfg, None, e.scenarios):
            size[sp.scenario_id] = sp.n_trips or 0
    todo.sort(key=lambda t: (-size.get(t[2], 0), -exps[t[0]].cfg.env.participation, t[2], t[3], t[1]))
    n, pending = 0, list(todo)
    for attempt in range(3):                   # a dead worker (e.g. a native libsumo crash) breaks the whole pool:
        if not pending:                        # finished tasks are kept, unfinished ones go to a fresh pool
            break
        broken = []
        with _pool(len(pending), workers=nw) as ex:
            futs = {ex.submit(dynamic_task, exps[ei].cfg.to_dict(), exps[ei].suite, p, s, k,
                              str(exps[ei].cfg.path(exps[ei].cfg.benchmark.out_dir)), exps[ei].exp): (ei, p, s, k)
                    for ei, p, s, k in pending}
            for f in as_completed(futs):
                key = futs[f]
                try:
                    r = f.result()
                except BrokenProcessPool as err:
                    broken.append((key, err))
                    continue
                except Exception as err:        # recorded, never silently dropped
                    r = _failed(exps, key, f"task error: {err}")
                done[key] = r
                n += 1
                log(json.dumps({"done": n, "of": len(todo), "exp": r.get("experiment_id"),
                                **{k: r.get(k) for k in ("policy", "scenario", "seed_offset", "status", "wall_s",
                                                         "error")}, "complete": (r.get("quality") or {}).get("complete"),
                                "peak_mem": r.get("peak_mem"), "elapsed_s": round(time.time() - t0)}))
        pending = [key for key, _ in broken]
        if pending:
            log(json.dumps({"pool_broken": len(pending), "attempt": attempt + 1, "error": str(broken[0][1])[:300]}))
    for key in pending:                        # still unfinished after the retries
        done[key] = _failed(exps, key, "worker process crashed repeatedly (pool broken)")
    results = []
    for ei, e in enumerate(exps):
        recs = [done[(ei, p, s, k)] for s in e.scenarios for k in e.seeds for p in e.policies if (ei, p, s, k) in done]
        meta = {"experiment_id": e.exp, "suite": e.suite, "policies": e.policies, "scenarios": e.scenarios,
                "seeds": e.seeds, "config": e.cfg.name, "config_hash": e.cfg.hash(),
                "checkpoints": checkpoint_status(e.cfg), "batch_window_s": e.cfg.benchmark.batch_window_s,
                "forecast_mode": e.cfg.env.forecast_mode, "forecast_checkpoint": e.cfg.env.forecast_checkpoint,
                "participation": e.cfg.env.participation, "max_participants": e.cfg.env.max_participants,
                "compliance": e.cfg.env.compliance, "max_drain_s": e.cfg.env.max_drain_s,
                "time_to_teleport_s": e.cfg.env.time_to_teleport_s, "code": e.code,
                "finished": time.strftime("%Y%m%dT%H%M%S")}
        res = {"meta": meta, "runs": recs, "wall_s": round(time.time() - t0, 1)}
        (e.cfg.path(e.cfg.benchmark.out_dir) / e.exp / "results.json").write_text(json.dumps(res, indent=1, default=str))
        results.append(res)
    return results


def run(cfg: Config, suite: str, policies: list | None = None, scenarios: list | None = None,
        seeds: list | None = None, log=print, resume: bool = True) -> dict:
    from ..runtime import load_network
    load_network(cfg)                          # build the network cache once, before workers race for it
    e = prepare(cfg, suite, policies, scenarios, seeds)
    if suite != "static":
        return run_many([e], resume=resume, log=log)[0]
    stamp = time.strftime("%Y%m%dT%H%M%S")
    meta = {"experiment_id": e.exp, "suite": suite, "policies": e.policies, "scenarios": e.scenarios,
            "seeds": e.seeds, "config": cfg.name, "config_hash": cfg.hash(), "checkpoints": checkpoint_status(cfg),
            "started": stamp, "code": e.code}
    log(json.dumps({"benchmark": meta}, default=str))
    t0 = time.time()
    d = cfg.to_dict()
    with _pool(len(e.scenarios), cfg) as ex:
        rows = [f.result() for f in as_completed([ex.submit(static_task, d, s, e.policies) for s in e.scenarios])]
    res = {"meta": meta, "static": sorted(rows, key=lambda r: r["scenario"]), "wall_s": round(time.time() - t0, 1)}
    out = cfg.path(cfg.benchmark.out_dir) / e.exp
    out.mkdir(parents=True, exist_ok=True)
    (out / f"static_{stamp}.json").write_text(json.dumps(res, indent=1, default=str))
    return res
