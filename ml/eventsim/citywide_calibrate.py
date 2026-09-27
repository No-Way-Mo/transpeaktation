"""Background-demand calibration against observed TomTom speeds (data generation support; no model training).

    python -m eventsim.citywide_calibrate run    [--levels 6000 10000 14000 18000 --day 2026-09-26 --hours 6 7 8]
    python -m eventsim.citywide_calibrate report

Simulates no-event runs on network v3 for the observed day (with the verified closures active that day) at
several background demand levels, then compares simulated speed with observed TomTom speed on the same canonical
segments and local hours. Output data/sf_citywide/calibration/calibration.json is read by sampler v3 (plan) to
centre the background demand range. Observed traffic is only compared against, never written into synthetic data.

Limits (stated in the output): observed hours are whatever the poller has recorded (a Saturday early morning at
first), TomTom speeds are probe-based segment averages, and demand is identifiable only if simulated speed
actually responds to the demand level in those hours.
"""
from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from .config import KMH_TO_MPH, MPS_TO_MPH, SF_TZ, TS_DIR, BUCKET_S
from .citywide import ROOT, read, save
from . import citywide_batch as cb

OUT = ROOT / "calibration"
BATCH = "calib_v3"


def observed(day: str, hours: list[int]) -> pd.DataFrame:
    """Median observed TomTom speed (mph) per canonical segment and local hour, from the raw poll files."""
    mapping = read(ROOT / "prepared" / "source_mapping.json")["tomtom"]   # segment -> TomTom line key
    by_key = defaultdict(list)
    for sid, key in mapping.items():
        by_key[key].append(sid)
    rows = []
    for p in sorted((TS_DIR / "tomtom_flow").glob("20*.jsonl")):
        for line in p.open(encoding="utf-8"):
            r = json.loads(line)
            if not r.get("ok") or r.get("style") != "absolute":
                continue
            t = datetime.fromisoformat(r["polled_at"]).astimezone(SF_TZ)
            if t.date().isoformat() != day or t.hour not in hours:
                continue
            for item in r["lines"]:
                if item[0] in by_key and item[1] is not None:
                    for sid in by_key[item[0]]:
                        rows.append((sid, t.hour, float(item[1]) * KMH_TO_MPH))
    df = pd.DataFrame(rows, columns=["road_segment_id", "hour", "obs_mph"])
    return df.groupby(["road_segment_id", "hour"], as_index=False).obs_mph.median()


def plan(levels: list[float], day: str, hours: list[int], seed: int) -> dict:
    out = cb.batch_dir(BATCH)
    if (out / "scenarios.json").exists():
        return read(out / "scenarios.json")
    review = read(cb.latest_review())
    begin, end = (min(hours) * 3600 - 1800), (max(hours) + 1) * 3600 + 1800
    concurrent = []
    for c in review["cases"]:
        if c["status"] == "verified":
            concurrent += cb.restrictions_on(review, c["case_num"], day, begin, end, "concurrent_permit")
    rng = np.random.default_rng(seed)
    fams, runs = [], []
    for i, level in enumerate(levels):
        fam = cb.sample_family(np.random.default_rng(seed), "portola", "full", i, BATCH, 3)  # structure only
        fam.update(family_id=f"{BATCH}_level{int(level)}", family_group="calibration", event_key="none", date=day,
                   window="calibration")
        fam["background"].update(vph_peak=float(level), profile="weekend", profile_jitter=1.0)
        fam["network"] = {"tls_cycle_s": 90, "signal_control": "static"}
        fam["driver"] = {"tau": 1.2, "sigma": 0.45, "speed_dev": 0.1, "min_gap": 2.5}
        fam["time"] = {"sim_begin_s": begin, "analysis_begin_s": begin + 1800, "depart_end_s": end - 1800, "sim_end_s": end}
        fam["public_hours_s"] = [begin, end]
        fam["n_event_restrictions"], fam["n_concurrent_restrictions"] = 0, len(concurrent)
        fams.append(fam)
        runs.append({"run_id": f"{fam['family_id']}_control", "family_id": fam["family_id"], "family_group": "calibration",
                     "event_key": "none", "with_event": False, "seed": int(rng.integers(1, 2**31 - 1)),
                     "restrictions": concurrent})
    scen = {"schema_version": 3, "sampler_version": 3, "batch": BATCH, "network_dir": cb.NET_V3,
            "review_version": cb.latest_review().stem, "trigger_radius_m": cb.TRIGGER_RADIUS_M,
            "created_at": datetime.now(timezone.utc).isoformat(), "families": fams, "runs": runs,
            "profiles": cb.PROFILES, "calibration": {"day": day, "hours": hours, "levels": levels},
            "provenance": "calibration runs: no event, same seed per level; compared with observed TomTom speeds"}
    save(out / "scenarios.json", scen)
    return scen


def compare(day: str, hours: list[int]) -> dict:
    scen = read(cb.batch_dir(BATCH) / "scenarios.json")
    obs = observed(day, hours)
    bc = cb.BatchContext(BATCH)
    ids = np.asarray(bc.base.seg_ids)
    rows = []
    for fam, run in zip(scen["families"], scen["runs"]):
        d = bc.dir / "runs" / run["run_id"]
        if not (d / "summary.json").exists():
            continue
        with np.load(d / "measurements.npz") as m:
            speed, sampled = m["speed"].astype(float), np.nan_to_num(m["sampledSeconds"].astype(float))
        t = fam["time"]
        local_h = (t["sim_begin_s"] + np.arange(speed.shape[0]) * BUCKET_S) // 3600
        for h in hours:
            b = np.flatnonzero(local_h == h)
            if not len(b):
                continue
            # vehicle-weighted mean speed over the hour's buckets, only where vehicles were sampled
            w = sampled[b]
            v = np.where(w.sum(0) > 0, (np.nan_to_num(speed[b]) * w).sum(0) / np.maximum(w.sum(0), 1e-9), np.nan)
            sim = pd.DataFrame({"road_segment_id": ids, "sim_mph": v * MPS_TO_MPH, "hour": h}).dropna()
            j = sim.merge(obs[obs.hour == h], on=["road_segment_id", "hour"])
            rows.append({"level": fam["background"]["vph_peak"], "hour": h, "segments": len(j),
                         "sim_median_mph": float(j.sim_mph.median()), "obs_median_mph": float(j.obs_mph.median()),
                         "median_ratio_sim_obs": float((j.sim_mph / j.obs_mph).median()),
                         "mae_mph": float((j.sim_mph - j.obs_mph).abs().mean()),
                         "teleports": read(d / "summary.json")["teleports"].get("total", 0)})
    df = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / "comparison.csv", index=False)
    by = df.groupby("level").agg(ratio=("median_ratio_sim_obs", "mean"), mae=("mae_mph", "mean"),
                                 segments=("segments", "mean")).reset_index().sort_values("level")
    # identifiability: does simulated speed respond to demand in these hours?
    spread = float(by.ratio.max() - by.ratio.min())
    identifiable = spread >= 0.05
    best = by.iloc[(by.ratio - 1).abs().argmin()]
    # interpolate the level where the ratio crosses 1 (ratio falls as demand rises), if bracketed
    level = float(best.level)
    if identifiable and (by.ratio.max() >= 1 >= by.ratio.min()):
        xs, ys = np.log(by.level.to_numpy()), by.ratio.to_numpy()
        order = np.argsort(ys)
        level = float(np.exp(np.interp(1.0, ys[order], xs[order])))
    res = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "day": day, "hours": hours,
           "by_level": by.to_dict("records"), "ratio_spread_across_levels": spread,
           "demand_identifiable": bool(identifiable),
           "calibrated_vph_peak": level if identifiable else None,
           "fallback_vph_peak_range": [9_000, 16_000],
           "systematic_speed_bias_ratio": float(best.ratio),
           "caveats": ["observed hours are an early Saturday morning only (the poller started today)",
                       "TomTom speeds are probe averages over provider lines snapped to segments; SUMO speeds are "
                       "vehicle-weighted edge means (includes signal and stop delay)",
                       "a ratio away from 1 that does not change with demand is a network/speed-model bias "
                       "(free-flow speeds, stops, signals), not a demand signal"]}
    save(OUT / "calibration.json", res)
    return res


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("stage", choices=["run", "report"])
    p.add_argument("--levels", type=float, nargs="*", default=[6000, 10000, 14000, 18000])
    p.add_argument("--day", default="2026-09-26")
    p.add_argument("--hours", type=int, nargs="*", default=[6, 7, 8])
    p.add_argument("--seed", type=int, default=11)
    p.add_argument("--workers", type=int, default=4)
    a = p.parse_args()
    t0 = time.time()
    if a.stage == "run":
        plan(a.levels, a.day, a.hours, a.seed)
        sim = cb.simulate(BATCH, a.workers, None, False)
        if sim["failed"]:
            raise SystemExit(json.dumps(sim, indent=1))
    res = compare(a.day, a.hours)
    print(json.dumps({"elapsed_s": round(time.time() - t0, 1), **res}, indent=1, default=str))


if __name__ == "__main__":
    main()
