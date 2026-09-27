"""One-command pipeline for a large citywide synthetic batch (data generation only; no model training).

    python -m eventsim.citywide_pipeline preflight --batch b3_main --families-per-event 12 --seeds 2 --workers 6
    python -m eventsim.citywide_pipeline verify    --workers 8                 # small v3 batch + quality gate
    python -m eventsim.citywide_pipeline run       --batch b3_main --families-per-event 12 --seeds 2 --workers 6

`run` = preflight -> gate (the verification batch must have passed) -> plan (frozen, sampler v3) -> simulate
(resumable: re-run the same command after an interruption) -> report -> export -> readiness. Every stage is
idempotent. Nothing here trains a model or writes to live databases.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .citywide import ROOT, read, save
from . import citywide_batch as cb

VERIFY_BATCH = "b31_verify"   # sampler v3.1 (attendance + requests); b3_verify was the v3.0 check
# Quality gate for the verification batch (all runs):
GATE = {"max_unfinished_share": 0.001,         # trips still driving at the window end / trips, per run (no-route: 0)
        "max_teleports_per_1k": 10.0,           # per run
        "max_closed_entries_steady": 0,         # total, steady state (>= 20 min after a closure opens)
        "max_review_runs_share": 0.0}           # share of runs flagged review
DISK_MARGIN = 1.5


def preflight(batch: str | None, families_per_event: int, seeds: int, workers: int) -> dict:
    checks, problems = {}, []
    from .sumonet import sumo_bin
    import subprocess
    try:
        v = subprocess.run([sumo_bin("sumo"), "--version"], capture_output=True, text=True).stdout.splitlines()[0]
        checks["sumo"] = v
    except Exception as e:
        problems.append(f"SUMO not runnable: {e}")
    net = ROOT / cb.NET_V3 / "network.json"
    checks["network_v3"] = read(net) if net.exists() else None
    if not net.exists():
        problems.append("network v3 missing: python -m eventsim.citywide_batch network-v3")
    elif checks["network_v3"]["accepted_closure_segments_absorbed"]:
        problems.append("network v3 still absorbs accepted closure segments")
    rv = ROOT / "prepared" / "closure_review_v3.json"
    checks["closure_review"] = read(rv)["case_status"] if rv.exists() else None
    if not rv.exists():
        problems.append("closure review v3 missing: python -m eventsim.citywide review --review-version closure_review_v3")
    cal = ROOT / "calibration" / "calibration.json"
    checks["demand"] = cb.demand_range()[1]
    if not cal.exists():
        problems.append("no demand calibration: python -m eventsim.citywide_calibrate run")
    n_runs = len(cb.EVENT_POOL_V3) * families_per_event * seeds * 2
    est = _estimate(n_runs, workers)
    checks["estimate"] = est
    free_gb = shutil.disk_usage(ROOT).free / 2**30
    checks["disk_free_gb"] = round(free_gb, 1)
    if est["disk_gb"] * DISK_MARGIN > free_gb:
        problems.append(f"not enough disk: need ~{est['disk_gb'] * DISK_MARGIN:.0f} GB with margin, {free_gb:.0f} GB free")
    try:
        import psutil
        ram = psutil.virtual_memory().available / 2**30
        checks["ram_available_gb"] = round(ram, 1)
        if est["peak_ram_gb"] > 0.8 * ram:
            problems.append(f"{workers} workers need ~{est['peak_ram_gb']} GB RAM, {ram:.1f} GB available: lower --workers")
    except ImportError:
        pass
    if batch and (cb.batch_dir(batch) / "scenarios.json").exists():
        checks["batch_exists"] = "planned (will resume)"
    return {"ok": not problems, "problems": problems, "checks": checks}


def _estimate(n_runs: int, workers: int) -> dict:
    """Cost from the most recent measured batch quality table (v3 verification if present, else b2_bench)."""
    for b in (VERIFY_BATCH, "b2_bench"):
        q = cb.batch_dir(b) / "quality.csv"
        if q.exists():
            df = pd.read_csv(q)
            k = float((df.runtime_s / (df.trips * df.hours)).median())
            cpu_h = n_runs * k * float(df.trips.mean()) * float(df.hours.mean()) / 3600
            exp = cb.batch_dir(b) / "export" / "manifest.json"
            exp_mb = float(np.median([f["mb"] for f in read(exp)["files"] if f["path"].startswith("sim_")])) if exp.exists() else 10.0
            return {"from_batch": b, "runs": n_runs, "cpu_hours": round(cpu_h, 1),
                    "wall_hours": round(cpu_h / workers, 1), "workers": workers,
                    "peak_ram_gb": round(workers * float(df.peak_rss_mb.max()) * 1.2 / 1024, 1),
                    # + per-run network variants (closures baked in, ~60 MB each), shared by runs with the same
                    #   event/window/event-or-control/signal regime: at most events x 3 x 2 x 2
                    "disk_gb": round((n_runs * (float(df.disk_mb.mean()) + exp_mb)
                                      + min(n_runs, len(cb.EVENT_POOL_V3) * 3 * 2 * 2) * 60) / 1024, 1)}
    return {"from_batch": None, "runs": n_runs, "cpu_hours": None, "wall_hours": None, "workers": workers,
            "peak_ram_gb": round(workers * 0.9, 1), "disk_gb": round(n_runs * 0.03, 1)}


def gate_result() -> dict:
    q = cb.batch_dir(VERIFY_BATCH) / "quality.csv"
    if not q.exists():
        return {"passed": False, "reason": f"run `python -m eventsim.citywide_pipeline verify` first"}
    df = pd.read_csv(q)
    scen = read(cb.batch_dir(VERIFY_BATCH) / "scenarios.json")
    fails = []
    if len(df) < len(scen["runs"]):
        fails.append(f"only {len(df)}/{len(scen['runs'])} verification runs finished")
    share = (df.unfinished - df.not_inserted) / df.trips   # trips.csv counts never-inserted trips as unfinished
    if (share > GATE["max_unfinished_share"]).any():
        fails.append(f"still-driving share > {GATE['max_unfinished_share']:.1%} in "
                     f"{df.run_id[share > GATE['max_unfinished_share']].tolist()}")
    if (df.not_inserted > 0).any():
        fails.append(f"not-inserted/no-route trips in {df.run_id[df.not_inserted > 0].tolist()}")
    if (df.teleports_per_1k > GATE["max_teleports_per_1k"]).any():
        fails.append(f"teleports > {GATE['max_teleports_per_1k']}/1k in {df.run_id[df.teleports_per_1k > GATE['max_teleports_per_1k']].tolist()}")
    if df.closed_entries_steady.sum() > GATE["max_closed_entries_steady"]:
        fails.append(f"{df.closed_entries_steady.sum():.0f} steady-state closed-road entries")
    if (df.quality_flag == "review").mean() > GATE["max_review_runs_share"]:
        fails.append(f"{int((df.quality_flag == 'review').sum())} runs flagged review")
    return {"passed": not fails, "failures": fails, "gate": GATE, "runs": len(df),
            "teleports_per_1k_median": float(df.teleports_per_1k.median()),
            "teleports_per_1k_max": float(df.teleports_per_1k.max()),
            "closed_entries_onset_total": float(df.closed_entries_onset.sum())}


def verify(workers: int, seed: int) -> dict:
    """Small sampler-v3 batch across all events and windows: the evidence that fixes work before scaling."""
    if not (cb.batch_dir(VERIFY_BATCH) / "scenarios.json").exists():
        cb.plan(VERIFY_BATCH, 1, 1, seed, None, None, 3)
    sim = cb.simulate(VERIFY_BATCH, workers, None, False)
    cb.report(VERIFY_BATCH)
    cb.export(VERIFY_BATCH)
    g = gate_result()
    save(cb.batch_dir(VERIFY_BATCH) / "gate.json", g)
    return {"simulate": sim, "gate": g}


def run(batch: str, families_per_event: int, seeds: int, workers: int, seed: int, force_gate: bool,
        requests: str | None = None) -> dict:
    if batch in (VERIFY_BATCH, "b3_verify") or batch.startswith("b2"):
        raise SystemExit("choose a new batch id for the large batch")
    pf = preflight(batch, families_per_event, seeds, workers)
    if not pf["ok"]:
        raise SystemExit("preflight failed:\n- " + "\n- ".join(pf["problems"]))
    g = gate_result()
    if not g["passed"] and not force_gate:
        raise SystemExit("verification gate not passed:\n- " + "\n- ".join(g.get("failures") or [g.get("reason", "")]))
    out = cb.batch_dir(batch)
    if not (out / "scenarios.json").exists():
        cb.plan(batch, families_per_event, seeds, seed, None, None, 3, requests)
    manifest = {"batch": batch, "started_at": datetime.now(timezone.utc).isoformat(), "preflight": pf, "gate": g,
                "gate_overridden": bool(force_gate and not g["passed"]), "command": " ".join(sys.argv)}
    save(out / "pipeline_manifest.json", manifest)
    sim = cb.simulate(batch, workers, None, False)
    rep = cb.report(batch)
    exp = cb.export(batch)
    rd = readiness_v3(batch, families_per_event, seeds, workers)
    manifest.update(finished_at=datetime.now(timezone.utc).isoformat(), simulate=sim, report=rep, export=exp,
                    readiness=rd["report"])
    save(out / "pipeline_manifest.json", manifest)
    return {"batch": batch, "simulate": sim, "quality_flags": rep["quality_flags"], "readiness": rd["report"]}


OCEAN_BOX = (-122.4605, -122.4575, 37.7240, 37.7250)   # the v1/v2 Ocean Ave parallel-edge hotspot


def _batch_quality(batch: str) -> pd.DataFrame | None:
    q = cb.batch_dir(batch) / "quality.csv"
    return pd.read_csv(q) if q.exists() else None


def _teleports_in_box(batch: str, box) -> int:
    nodes = read(ROOT / "prepared" / "patch.json")["nodes"]
    n = 0
    for p in (cb.batch_dir(batch) / "runs").glob("*/teleports.csv"):
        t = pd.read_csv(p)
        for j in t.junction.astype(str):
            ll = nodes.get(j.split("_")[0])
            if ll and box[0] <= ll[0] <= box[1] and box[2] <= ll[1] <= box[3]:
                n += 1
    return n


def readiness_v3(target_batch: str, families_per_event: int, seeds: int, workers: int) -> dict:
    """reports/citywide_data_readiness_v3.md: evidence per fixed problem (v2 benchmark vs v3 verification),
    sourced-vs-assumed inputs, gate status, cost of the big batch and the exact command to run it."""
    from .config import REPORTS_DIR
    v2, v3 = _batch_quality("b2_bench"), _batch_quality(VERIFY_BATCH)
    if v3 is None:
        raise SystemExit("run the verification batch first")
    g = gate_result()
    net = read(ROOT / cb.NET_V3 / "network.json")
    rv3 = read(ROOT / "prepared" / "closure_review_v3.json")
    rv2 = read(ROOT / "prepared" / "closure_review_v2.json")
    cal = read(ROOT / "calibration" / "calibration.json") if (ROOT / "calibration" / "calibration.json").exists() else {}
    scen = read(cb.batch_dir(VERIFY_BATCH) / "scenarios.json")
    pf = preflight(target_batch, families_per_event, seeds, workers)
    est = pf["checks"]["estimate"]
    cw = pd.read_csv(ROOT / cb.NET_V3 / "crosswalk.csv")
    lanes_assumed = int((~cw.lanes_source.astype(str).str.startswith("osm")).sum())

    def stat(df, col, fn="median"):
        return "n/a" if df is None else f"{getattr(df[col], fn)():.1f}"
    fol2 = v2[v2.run_id.str.contains("folsom") & v2.run_id.str.endswith("event")].iloc[0] if v2 is not None else None
    fol3 = v3[v3.run_id.str.contains("folsom") & v3.run_id.str.endswith("event")].iloc[0]
    fam3 = next(f for f in scen["families"] if f["event_key"] == "folsom")
    ready = g["passed"] and pf["ok"]
    L = [
        "# Citywide synthetic data v3: readiness for the large batch", "",
        f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} by "
        "`python -m eventsim.citywide_pipeline readiness`. **Data generation only; no model is trained.** All traffic is "
        "synthetic (SUMO) on the real SF road graph, with real permitted closures and dates. It is not observed "
        "traffic and not event ground truth.", "",
        "## Verdict", "",
        (f"**Ready to run.** The v3 verification batch passed the quality gate ({g['runs']} runs) and preflight passed. "
         f"Command below." if ready else
         "**Not ready.** " + "; ".join((g.get("failures") or [g.get("reason", "")]) + pf["problems"])), "",
        "## The five problems: v2 benchmark vs v3 verification", "",
        f"| Problem | Fix (v3) | v2 (`b2_bench`) | v3.1 (`{VERIFY_BATCH}`) |", "|---|---|---|---|",
        f"| Parallel roads (Ocean Ave etc.) cause artificial jams and teleports | network v3 merges {net['merged_parallel']} "
        f"parallel OSM edges into one edge carrying both carriageways' lanes | teleports/1k median {stat(v2, 'teleports_per_1k')}, "
        f"max {stat(v2, 'teleports_per_1k', 'max')}; Ocean Ave hotspot {_teleports_in_box('b2_bench', OCEAN_BOX) if v2 is not None else 'n/a'} | "
        f"median {stat(v3, 'teleports_per_1k')}, max {stat(v3, 'teleports_per_1k', 'max')}; Ocean Ave hotspot "
        f"{_teleports_in_box(VERIFY_BATCH, OCEAN_BOX)} |",
        f"| Extreme event load overwhelms the network; ride-hail blocks lanes | event vehicles capped at "
        f"{cb.MAX_EVENT_VEHICLES:,}; spreads widened so peak inflow ≤ {cb.MAX_PEAK_ARRIVALS_VPH:,} veh/h and outflow ≤ "
        f"{cb.MAX_PEAK_DEPARTURES_VPH:,} veh/h; ride-hail stops pull off the lane | Folsom event: "
        f"{'n/a' if fol2 is None else f'{fol2.trips:,} trips, {fol2.teleports:,} teleports, {fol2.unfinished} unfinished'} | "
        f"Folsom event ({fam3['event']['vehicle_trips']:,} veh, ±{fam3['event']['arrival_sigma_min']:.0f} min): "
        f"{fol3.trips:,} trips, {fol3.teleports:,} teleports ({fol3.teleports_per_1k:.1f}/1k), {fol3.unfinished} unfinished |",
        f"| Mid-run closures leak (vehicles past the rerouting point) | rerouter triggers on every edge within "
        f"{cb.TRIGGER_RADIUS_M:.0f} m, so vehicles re-plan at their next edge after the closure opens | steady-state "
        f"entries {stat(v2, 'closed_entries_steady', 'sum')}, onset {stat(v2, 'closed_entries_onset', 'sum')} | steady "
        f"{stat(v3, 'closed_entries_steady', 'sum')}, onset {stat(v3, 'closed_entries_onset', 'sum')} |",
        f"| Unresolved closure mappings; closure pieces merged into junctions | review v3 (spacing-insensitive names; "
        f"alleys/plazas with no drivable road); network v3 never absorbs accepted closure segments | "
        f"{rv2['row_decisions'].get('needs_review', 0)} rows need review; 40 accepted segments absorbed | "
        f"{rv3['row_decisions'].get('needs_review', 0)} rows need review (evidence CSV); "
        f"{net['accepted_closure_segments_absorbed']} absorbed |",
        f"| Inputs are assumptions | public hours sourced; event demand from each event's attendance (API interface: "
        f"`event_attendance_v1.csv`); all other demand as trip requests (origin/destination/time, the client format); "
        f"network speeds checked against TomTom; "
        f"signal regime varied (fixed/actuated) | 6/8 event hours assumed | see table below |", "",
        "## Inputs: sourced vs assumed (v3)", "",
        "| Input | Status | Evidence |", "|---|---|---|",
    ]
    for k, ev in cb.EVENT_POOL_V3.items():
        L.append(f"| {k} hours {ev['hours'][0]}–{ev['hours'][1]} | {ev['hours_confidence']} confidence | {ev['hours_source']} |")
        from .citywide_demand import attendance_for
        a = attendance_for(ev["case_num"])
        L.append(f"| {k} attendance {int(a['attendance']):,} | {'estimate' if a['is_estimate'] else 'published figure'} "
                 f"({a['method']}) | {a['source']} |")
    if cal:
        levels_txt = ", ".join("{:.0f} vph→{:.3f}".format(r["level"], r["ratio"]) for r in cal["by_level"])
        L.append("| Non-event demand | trip requests (origin, destination, departure time) | synthetic stand-in requests "
                 "saved per run (`runs/<run>/requests.parquet`); pass real client requests with `--requests` and they "
                 "replace the stand-in one-for-one |")
        L.append(f"| Stand-in request volume | {'calibrated' if cal.get('demand_identifiable') else 'not identifiable from observed data yet'} | "
                 f"TomTom vs SUMO on {cal['day']} hours {cal['hours']}: sim/obs speed ratio "
                 f"{levels_txt} (spread "
                 f"{cal['ratio_spread_across_levels']:.3f}); speeds ~{100 * (cal['systematic_speed_bias_ratio'] - 1):+.0f}% vs "
                 "TomTom at every level, so the network speed model agrees but early-morning demand can't be identified |")
    L += [f"| Signal timing | assumption, varied | fixed 90 s cycles vs SUMO actuated control, sampled per family (no SF signal plans in the data) |",
          f"| Lane counts | assumption for {lanes_assumed:,} of {len(cw):,} segments | OSM `lanes` where tagged, class defaults otherwise; no lane source for SF is pulled yet |",
          "| Drive share, occupancy, ride-hail share, parking radius | assumption, varied | converts attendance to vehicles; recorded per family |",
          f"| Event vehicle cap {cb.MAX_EVENT_VEHICLES:,} | assumption (parking/road capacity) | binds for the largest events; "
          "`vehicles_before_cap` recorded per family |",
          f"| Attendance for the other {len(pd.read_csv(ROOT / 'prepared' / 'event_attendance_v1.csv')) - 8} verified events | category estimates | `prepared/event_attendance_v1.csv` "
          "(block party 300, farmers market 2,000, night market 10,000, …); the API replaces them |", "",
          f"## Verification batch (`{VERIFY_BATCH}`)", ""]
    cols = ["run_id", "window", "hours", "trips", "unfinished", "not_inserted", "teleports", "teleports_per_1k",
            "closed_entries_steady", "closed_entries_onset", "runtime_s", "peak_rss_mb", "quality_flag"]
    t = v3[cols].copy()
    t["run_id"] = t.run_id.str.replace(f"{VERIFY_BATCH}_", "", regex=False)
    L += cb._md_table(t) + ["", f"Gate: {json.dumps(GATE)} → **{'passed' if g['passed'] else 'failed'}**"
                                + ("" if g["passed"] else f": {g.get('failures')}"), "",
          "## Large batch", "",
          f"- Plan: {len(cb.EVENT_POOL_V3)} events × {families_per_event} families × {seeds} seeds × (event + control) = "
          f"{est['runs']} runs, windows rotating arrival / departure+recovery / full day.",
          f"- Estimated cost (from `{est['from_batch']}`): ~{est['cpu_hours']} CPU-h → ~{est['wall_hours']} h wall at "
          f"{workers} workers, ~{est['peak_ram_gb']} GB RAM, ~{est['disk_gb']} GB disk ({pf['checks']['disk_free_gb']} GB free).",
          "- Command (resumable; re-run the same line after an interruption):", "",
          "```sh", f"cd ml && python -m eventsim.citywide_pipeline run --batch {target_batch} "
          f"--families-per-event {families_per_event} --seeds {seeds} --workers {workers}", "```", "",
          "- Output: `ml/data/sf_citywide/batches/<batch>/export/sim_<run>.parquet` (canonical IDs, mph, 10-min UTC, "
          "congestion ratio, observed/closed/in_sumo masks, warmup/demand/drain phase, run/family IDs, synthetic=True), "
          "`segments.parquet` (per-segment gaps incl. merged_parallel), `quality.csv` (per-run quality_flag).", "",
          "## Still open (does not block generation, limits realism)", "",
          "- Real client requests don't exist yet: the stand-in request volume stays uncalibrated until requests or "
          "busier observed hours are available. To calibrate the stand-in against traffic, re-run "
          "`python -m eventsim.citywide_calibrate run --hours 12 13 14 17 18` later (sampler v3 then centres on it; "
          "calibration batches are frozen, so remove `batches/calib_v3` first or give a new day).",
          f"- {rv3['row_decisions'].get('needs_review', 0)} closure rows need a human decision: "
          "`prepared/closure_review_v3_needs_review.csv` (their cases stay out of the scenario pool).",
          "- Attendance is organisers' claims or assumptions; lanes and signals are assumptions; no measured event "
          "traffic has validated any run (Folsom 2026-09-27 is the first chance)."]
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / "citywide_data_readiness_v3.md"
    path.write_text("\n".join(L) + "\n", encoding="utf-8")
    return {"report": str(path), "ready": ready, "gate": g, "preflight_ok": pf["ok"], "estimate": est}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("stage", choices=["preflight", "verify", "run", "gate", "readiness"])
    p.add_argument("--batch")
    p.add_argument("--families-per-event", type=int, default=12)
    p.add_argument("--seeds", type=int, default=2)
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--seed", type=int, default=2026)
    p.add_argument("--force-gate", action="store_true", help="run even if the verification gate failed (recorded)")
    p.add_argument("--requests", help="client trip requests (parquet/csv) to use as background demand")
    a = p.parse_args()
    t0 = time.time()
    if a.stage == "preflight":
        r = preflight(a.batch, a.families_per_event, a.seeds, a.workers)
    elif a.stage == "verify":
        r = verify(a.workers, a.seed)
    elif a.stage == "gate":
        r = gate_result()
    elif a.stage == "readiness":
        r = readiness_v3(a.batch or "b3_main", a.families_per_event, a.seeds, a.workers)
    else:
        if not a.batch:
            p.error("--batch is required for run")
        r = run(a.batch, a.families_per_event, a.seeds, a.workers, a.seed, a.force_gate, a.requests)
    print(json.dumps({"stage": a.stage, "elapsed_s": round(time.time() - t0, 1), **r}, indent=1, default=str))
    if a.stage == "preflight" and not r["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
