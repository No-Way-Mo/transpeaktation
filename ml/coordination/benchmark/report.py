"""Benchmark report: paired, episode-level comparison of each policy against forecast_only.

The unit of evidence is one (scenario, simulation seed) episode, a "block"; differences are paired within it. Road-
or vehicle-level samples are never pooled into confidence statements. With few blocks, results are reported as mean
and median paired difference, spread, win/loss counts and the worst regression, and are called inconclusive unless
every pair agrees.

Primary ranking (LOAD_BALANCING_BACKTEST_PLAN.md §4C, §7) uses only *common complete blocks*: blocks where every
compared policy ran, completed strictly (every in-scope vehicle arrived; no dropped trips, invalid routes, readback
mismatches, selector/forecast failures or unchosen fallbacks) and saw the identical demand, participants and
compliance draws. Nothing is silently dropped: every failure and censored run is listed, a policy with any failure is
not eligible to be called best, and a secondary common-horizon table (vehicle-hours through the same drain cap plus the
unfinished backlog) covers every successful block.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

BASE = "forecast_only"

# paired outcome metrics: (column, label, lower is better)
METRICS = [("vehicle_hours", "total in-scope vehicle-hours"),
           ("congested_h_scope", "in-scope vehicle-hours at <=50% free-flow"),
           ("congested_h_all", "all-vehicle hours at <=50% free-flow (mapped roads)"),
           ("stopped_h_scope", "in-scope stopped vehicle-hours"),
           ("pending_h_scope", "in-scope insertion-queue hours"),
           ("part_trip_s_mean", "participant mean trip s"), ("part_trip_s_p95", "participant p95 trip s"),
           ("other_trip_s_mean", "background mean trip s"), ("other_trip_s_p95", "background p95 trip s"),
           ("part_route_m_mean", "participant mean route m")]

# development success targets (plan §7), fixed before any run
TARGETS = {"vehicle_hours_reduction_pct_min": 5.0, "background_mean_worse_pct_max": 2.0,
           "participant_p95_worse_pct_max": 5.0}


def _md(df: pd.DataFrame, index: bool = True) -> str:
    """Markdown table without optional dependencies."""
    if index:
        df = df.reset_index()
    fmt = lambda v: "" if v is None or (isinstance(v, float) and np.isnan(v)) else (f"{v:.4g}" if isinstance(v, float) else str(v))
    lines = ["| " + " | ".join(map(str, df.columns)) + " |", "|" + "---|" * len(df.columns)]
    lines += ["| " + " | ".join(fmt(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join(lines)


def _quality(r: dict) -> dict:
    if r.get("quality"):
        return r["quality"]
    from .runner import quality
    return quality(r.get("summary") or {})


def flatten(res: dict) -> pd.DataFrame:
    rows = []
    for r in res["runs"]:
        s = r.get("summary") or {}
        o = s.get("outcomes", {})
        b = s.get("bench", {})
        c = s.get("congestion", {})
        i = s.get("identity", {})
        q = _quality(r) if r.get("status") == "ok" else {"complete": False, "failed_checks": [r.get("status")]}
        rows.append({
            "policy": r["policy"], "scenario": r["scenario"], "seed": r["seed_offset"], "status": r["status"],
            "complete": bool(q.get("complete")), "failed_checks": ",".join(q.get("failed_checks", [])),
            "error": r.get("error"),
            "vehicle_hours": s.get("in_scope_vehicle_hours"), "in_scope_vehicles": s.get("in_scope_vehicles"),
            "congested_h_scope": c.get("congested_h_scope"), "congested_h_all": c.get("congested_h_all"),
            "stopped_h_scope": c.get("stopped_h_scope"), "pending_h_scope": c.get("pending_h_scope"),
            "observed_h_scope": c.get("observed_h_scope"),
            "unfinished": s.get("unfinished"), "terminated": s.get("terminated"), "teleports": s.get("teleports"),
            "dropped_trips": s.get("dropped_trips"), "readback_mismatch": s.get("route_readback_mismatch"),
            "forecast_failures": s.get("forecast_refresh_failures"),
            "participants": s.get("participants"), "decided": b.get("decided"), "trivial": s.get("trivial"),
            "noncompliant": s.get("noncompliant"),
            "non_fastest_share": b.get("non_fastest_share"), "invalid_route": s.get("invalid_route"),
            "unsupported": s.get("unsupported_fallback"), "selector_failures": b.get("selector_failures"),
            "unchosen_fallback": b.get("unchosen_fallback"), "off_route_cancelled": s.get("off_route_cancelled"),
            "part_trip_s_mean": o.get("participants", {}).get("trip_s_mean"),
            "part_trip_s_p95": o.get("participants", {}).get("trip_s_p95"),
            "part_arrived": o.get("participants", {}).get("arrived"),
            "other_trip_s_mean": o.get("others", {}).get("trip_s_mean"),
            "other_trip_s_p95": o.get("others", {}).get("trip_s_p95"),
            "other_arrived": o.get("others", {}).get("arrived"),
            "part_route_m_mean": o.get("participants", {}).get("route_m_mean"),
            "call_ms_p50": b.get("call_ms_p50"), "call_ms_p95": b.get("call_ms_p95"),
            "batch_delay_s_mean": b.get("batch_delay_s_mean"), "batch_size_mean": b.get("batch_size_mean"),
            "forecast_extra_travel_s_mean": b.get("forecast_extra_travel_s_mean"),
            "demand_sha": i.get("demand_sha"), "participants_sha": i.get("participants_sha"),
            "noncompliant_sha": i.get("noncompliant_sha"), "initial_running_sha": i.get("initial_running_sha"),
            "used_warm_state": s.get("used_warm_state"), "wall_s": r.get("wall_s"),
            "peak_mem_mb": ((r.get("peak_mem") or {}).get("self_mb") or 0) + ((r.get("peak_mem") or {}).get("children_mb") or 0)
            or None})
    return pd.DataFrame(rows)


def population_mismatches(df: pd.DataFrame) -> list[dict]:
    """Blocks whose successful runs did not all see the same demand, participants, compliance draws and initial
    running vehicles (equal counts are not enough)."""
    out = []
    ok = df[df.status == "ok"]
    for (sc, sd), g in ok.groupby(["scenario", "seed"]):
        for col in ("demand_sha", "participants_sha", "noncompliant_sha", "initial_running_sha"):
            vals = g[col].dropna().unique()
            if len(vals) > 1:
                out.append({"scenario": sc, "seed": sd, "field": col, "values": sorted(map(str, vals))})
    return out


def common_blocks(df: pd.DataFrame, policies: list, complete: bool = True) -> list[tuple]:
    """Blocks in which every listed policy has a successful (and, if `complete`, strictly complete) run with an
    identical population."""
    bad = {(m["scenario"], m["seed"]) for m in population_mismatches(df)}
    out = []
    for (sc, sd), g in df.groupby(["scenario", "seed"]):
        g = g[g.policy.isin(policies)]
        good = g[(g.status == "ok") & (g.complete if complete else True)]
        if set(good.policy) >= set(policies) and (sc, sd) not in bad:
            out.append((sc, sd))
    return sorted(out)


def paired(df: pd.DataFrame, metric: str, blocks: list | None = None, base: str = BASE) -> pd.DataFrame:
    ok = df[df.status == "ok"]
    if blocks is not None:
        keep = set(blocks)
        ok = ok[[(a, b) in keep for a, b in zip(ok.scenario, ok.seed)]]
    basev = ok[ok.policy == base].set_index(["scenario", "seed"])[metric]
    out = []
    for p in sorted(ok.policy.unique()):
        if p == base:
            continue
        x = ok[ok.policy == p].set_index(["scenario", "seed"])[metric]
        j = pd.concat([x, basev], axis=1, keys=["p", "b"]).dropna()
        if j.empty:
            continue
        d = j.p - j.b
        rel = 100 * d / j.b.replace(0, np.nan)
        out.append({"policy": p, "metric": metric, "pairs": len(d), "base_mean": j.b.mean(), "mean_diff": d.mean(),
                    "median_diff": d.median(), "std_diff": d.std(ddof=1) if len(d) > 1 else np.nan,
                    "mean_rel_pct": rel.mean(), "median_rel_pct": rel.median(), "worst_rel_pct": rel.max(),
                    "better": int((d < 0).sum()), "worse": int((d > 0).sum()), "tied": int((d == 0).sum()),
                    "verdict": ("better in every pair" if (d < 0).all() else "worse in every pair" if (d > 0).all()
                                else "inconclusive")})
    return pd.DataFrame(out)


def targets(pv: pd.DataFrame, policy: str) -> dict:
    """Plan §7 development targets on the common complete blocks (engineering targets, not guarantees)."""
    def get(metric, col):
        r = pv[(pv.policy == policy) & (pv.metric == metric)]
        return float(r[col].iloc[0]) if len(r) and pd.notna(r[col].iloc[0]) else None
    vh = get("vehicle_hours", "mean_rel_pct")
    vd, nb, nw = get("vehicle_hours", "mean_diff"), get("vehicle_hours", "better"), get("vehicle_hours", "worse")
    cg = get("congested_h_scope", "mean_rel_pct")
    bg = get("other_trip_s_mean", "mean_rel_pct")
    p95 = get("part_trip_s_p95", "mean_rel_pct")
    return {"vehicle_hours_reduction_pct": None if vh is None else -vh, "vehicle_hours_mean_diff": vd,
            "blocks_better": nb, "blocks_worse": nw,
            # a reduction counts only if the absolute and relative means agree and it wins at least 2/3 of blocks
            "consistent_reduction": bool(vh is not None and vd is not None and vh < 0 and vd < 0 and nb is not None
                                         and nb >= 2 * (nw or 0) and nb > 0),
            "congested_scope_reduction_pct": None if cg is None else -cg,
            "background_mean_change_pct": bg, "participant_p95_change_pct": p95,
            "meets_vehicle_hours_target": vh is not None and -vh >= TARGETS["vehicle_hours_reduction_pct_min"]
            and vd is not None and vd < 0,
            "lower_congestion": cg is not None and cg < 0,
            "background_ok": bg is None or bg <= TARGETS["background_mean_worse_pct_max"],
            "participant_p95_ok": p95 is None or p95 <= TARGETS["participant_p95_worse_pct_max"]}


def summarize(res: dict) -> dict:
    """Machine-readable verdicts used by the report and by the backtest's pre-declared selection rule."""
    df = flatten(res)
    pols = [p for p in res["meta"]["policies"] if not (df[df.policy == p].status == "unavailable").all()]
    blocks = common_blocks(df, pols, complete=True)
    pv = pd.concat([paired(df, m, blocks) for m, _ in METRICS], ignore_index=True) if blocks else pd.DataFrame()
    cons = {}
    for p, g in df.groupby("policy"):
        cons[p] = {"runs": int(len(g)), "ok": int((g.status == "ok").sum()), "complete": int(g.complete.sum()),
                   "unavailable": int((g.status == "unavailable").sum()), "failed": int((g.status == "failed").sum()),
                   "invalid_routes": int(pd.to_numeric(g.invalid_route, errors="coerce").fillna(0).sum()),
                   "selector_failures": int(pd.to_numeric(g.selector_failures, errors="coerce").fillna(0).sum()),
                   "unchosen_fallbacks": int(pd.to_numeric(g.unchosen_fallback, errors="coerce").fillna(0).sum()),
                   "dropped_trips": int(pd.to_numeric(g.dropped_trips, errors="coerce").fillna(0).sum()),
                   "readback_mismatch": int(pd.to_numeric(g.readback_mismatch, errors="coerce").fillna(0).sum()),
                   "unfinished": int(pd.to_numeric(g.unfinished, errors="coerce").fillna(0).sum()), "teleports": int(pd.to_numeric(g.teleports, errors="coerce").fillna(0).sum()),
                   "call_ms_p95_max": float(g.call_ms_p95.max()) if g.call_ms_p95.notna().any() else None}
    ranking = []
    if not pv.empty:
        vh = pv[pv.metric == "vehicle_hours"]
        ranking = [{"policy": BASE, "mean_diff_vehicle_hours": 0.0, "mean_rel_pct": 0.0}] + \
                  [{"policy": r.policy, "mean_diff_vehicle_hours": r.mean_diff, "mean_rel_pct": r.mean_rel_pct,
                    "verdict": r.verdict} for r in vh.itertuples()]
        ranking.sort(key=lambda r: r["mean_diff_vehicle_hours"])
    eligible = [r for r in ranking if cons.get(r["policy"], {}).get("runs")
                and cons[r["policy"]]["complete"] == cons[r["policy"]]["runs"]]
    return {"df": df, "blocks": blocks, "paired": pv, "constraints": cons, "ranking": ranking,
            "eligible": [r["policy"] for r in eligible], "best": eligible[0]["policy"] if eligible else None,
            "population_mismatches": population_mismatches(df),
            "targets": {p: targets(pv, p) for p in pols if p != BASE} if not pv.empty else {}}


def write(res: dict, path_md: Path, path_csv: Path) -> dict:
    S = summarize(res)
    df, pv, blocks = S["df"], S["paired"], S["blocks"]
    path_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path_csv, index=False)
    meta = res["meta"]
    ok = df[df.status == "ok"]
    cb = df[np.array([(a, b) in set(blocks) for a, b in zip(df.scenario, df.seed)], bool) & (df.status == "ok").to_numpy()]
    agg_cols = ["vehicle_hours", "congested_h_scope", "congested_h_all", "stopped_h_scope", "pending_h_scope",
                "part_trip_s_mean", "part_trip_s_p95", "other_trip_s_mean", "other_trip_s_p95", "unfinished",
                "teleports", "decided", "non_fastest_share", "call_ms_p95", "batch_delay_s_mean",
                "forecast_extra_travel_s_mean", "wall_s", "peak_mem_mb"]
    agg = cb.groupby("policy")[agg_cols].mean().round(3) if not cb.empty else pd.DataFrame()
    horizon = pd.concat([paired(df, m) for m in ("vehicle_hours", "congested_h_scope", "unfinished")],
                        ignore_index=True) if not ok.empty else pd.DataFrame()
    status = df.groupby(["policy", "status"]).size().unstack(fill_value=0)
    status["complete"] = df.groupby("policy").complete.sum()
    fails = df[(df.status != "ok") | ~df.complete][["policy", "scenario", "seed", "status", "failed_checks",
                                                     "unfinished", "teleports", "error"]]
    n_blocks = len(meta["scenarios"]) * len(meta["seeds"])
    L = [f"# Coordinated routing benchmark: `{meta['suite']}` · `{meta.get('experiment_id', '')}`", "",
         "> **Synthetic.** SUMO scenarios on the SF citywide network; demand, attendance and behaviour are assumptions.",
         "> Differences are realized in simulation under these assumptions, not measured on real streets.", "",
         f"- Scenarios ({len(meta['scenarios'])}): " + ", ".join(f"`{s}`" for s in meta["scenarios"]),
         f"- Simulation seeds: {meta['seeds']} · policies: {', '.join(f'`{p}`' for p in meta['policies'])}",
         f"- Forecast: `{meta['forecast_mode']}` ({meta['forecast_checkpoint']}) · participation "
         f"{meta['participation']} (cap {meta.get('max_participants')}) · compliance {meta['compliance']} · batch "
         f"window {meta['batch_window_s']} s · drain cap {meta.get('max_drain_s')} s · teleport after "
         f"{meta.get('time_to_teleport_s')} s",
         f"- RL checkpoints: {json.dumps(meta['checkpoints'])}", f"- Code: `{json.dumps(meta.get('code', {}))}`",
         f"- Wall time: {res.get('wall_s')} s", "",
         "## Run status", "", _md(status), "",
         f"Common complete blocks (every policy complete, identical population): **{len(blocks)} of {n_blocks}**"
         + (": " + ", ".join(f"`{a}` s{b}" for a, b in blocks) if blocks else ""), ""]
    if S["population_mismatches"]:
        L += ["**Population mismatches (blocks excluded):**", "", "```json",
              json.dumps(S["population_mismatches"], indent=1), "```", ""]
    if not fails.empty:
        L += ["### Failed, incomplete or censored runs (kept visible, excluded from the primary ranking)", "",
              _md(fails, index=False), ""]
    L += ["## Mean outcomes per policy (common complete blocks)", "",
          "vehicle_hours = realized time of every in-scope vehicle (participants and background, including insertion "
          "and batching waits), scored from the first decision. congested = vehicle-hours on mapped roads at speed <= "
          "50% of the road's free-flow speed; stopped = speed < 0.1 m/s; pending = in-scope vehicles waiting "
          "off-network for insertion. Trip times count from the scheduled departure.", "",
          _md(agg) if not agg.empty else "(no common complete blocks)", "",
          f"## Paired differences vs `{BASE}` on common complete blocks (policy minus baseline; negative = less)", "",
          _md(pv.round(4), index=False) if not pv.empty else "(no pairs)", "",
          "## Common-horizon check on every successful block (includes censored runs)", "",
          "Vehicle-hours through the same drain cap, congested hours and unfinished backlog; a policy that leaves more "
          "vehicles unfinished is not better because its completed trips look faster.", "",
          _md(horizon.round(4), index=False) if not horizon.empty else "(no pairs)", "",
          "## Ranking by paired total vehicle-hours (common complete blocks)", ""]
    for i, r in enumerate(S["ranking"], 1):
        L.append(f"{i}. `{r['policy']}`: {r['mean_diff_vehicle_hours']:+.3f} veh-h ({r['mean_rel_pct']:+.2f}%) vs "
                 f"{BASE}" + (f" ({r.get('verdict')})" if r.get("verdict") else ""))
    L += ["", f"**Best eligible policy on this suite: `{S['best']}`**" if S["best"] else "**No eligible policy.**",
          "(eligible = every run of the policy completed strictly). With this few blocks a small mean difference that "
          "is not consistent across pairs is inconclusive; 'better in every pair' is not a significance test.", "",
          "## Development targets (plan §7, fixed before the runs)", "", "```json",
          json.dumps({"targets": TARGETS, "per_policy": S["targets"]}, indent=1, default=str), "```", "",
          "## Constraints", "", "```json", json.dumps(S["constraints"], indent=1), "```", ""]
    path_md.parent.mkdir(parents=True, exist_ok=True)
    path_md.write_text("\n".join(L), encoding="utf-8")
    return {"best": S["best"], "ranking": S["ranking"], "blocks": len(blocks), "report": str(path_md),
            "csv": str(path_csv)}


def write_static(res: dict, path_md: Path) -> dict:
    L = ["# Coordinated routing benchmark: `static`", "",
         "Same prepared requests per scenario (forecast at the window start, empty ledger); no simulation after the "
         "choice. Allocation penalty is the selection score's concentration term, NOT predicted or measured congestion.", ""]
    for s in res["static"]:
        L += [f"## `{s['scenario']}`", "", f"participants {s['participants']}, multi-candidate requests "
              f"{s['multi_candidate_requests']}, valid-count histogram {s['valid_count_hist']}", ""]
        rows = [{"policy": p, **v} for p, v in s["policies"].items()]
        L += [_md(pd.DataFrame(rows), index=False), ""]
    path_md.parent.mkdir(parents=True, exist_ok=True)
    path_md.write_text("\n".join(L), encoding="utf-8")
    return {"report": str(path_md)}
