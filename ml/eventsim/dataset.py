"""Stage 4: training examples from simulated runs.

    python -m eventsim dataset --event castro [--row-frac 0.35]

1. Split at the scenario-family level *before* building windows (a family = closure/parameter setup, its
   seed variants and their no-event controls). Hard-test families always go to test.
2. For every run, generate causal provider-like observations (features.ObsModel), then for each forecast origin
   t, segment and horizon h in {10, 30, 60} min: persistence baseline, event-rule baseline, features, and the
   residual target  y = measured simulated travel time at t+h - persistence travel time.
   Rows exist only where the future bucket has a measurement (not empty), the segment is open and in SUMO.

Outputs: ml/data/<event>/dataset/<run_id>.npz, splits.json, feature_schema.json
"""
from __future__ import annotations

import json
import os
from concurrent.futures import ProcessPoolExecutor

import numpy as np

from .config import BUCKET_S, HORIZONS, event_dir
from .features import (FEATURES, ObsModel, Static, build_features, declared_estimate, event_rule, persistence,
                       true_travel_time)
from .simulate import Context

SPLIT_SEED = 0


def assign_splits(ctx: Context) -> dict[str, str]:
    fams = sorted(ctx.fams)
    hard = [f for f in fams if ctx.fams[f]["hard_test"]]
    rest = [f for f in fams if f not in hard]
    rng = np.random.default_rng(SPLIT_SEED)
    rng.shuffle(rest)
    n = len(rest)
    n_test = max(1, round(0.15 * n)) if n >= 3 else 0
    n_val = max(1, round(0.15 * n)) if n >= 3 else 0
    split = {f: "test" for f in hard}
    for i, f in enumerate(rest):
        split[f] = "test" if i < n_test else "val" if i < n_test + n_val else "train"
    return split


def build_run(ev_key: str, run: dict, split: str, row_frac: float) -> dict:
    ctx = Context(ev_key)
    st = Static(ctx)
    fam = ctx.fams[run["family_id"]]
    t_cfg = ctx.scen["time"]
    d = ctx.dir / "runs" / run["run_id"]
    m = np.load(d / "measurements.npz")
    true_tt, measured = true_travel_time(m["speed"].astype(float), m["sampledSeconds"].astype(float), st.length)
    closed = m["closed"].astype(bool)
    T = true_tt.shape[0]
    obs = ObsModel(st, fam["observation"], run["seed"] + 2, T)
    est = declared_estimate(fam, run["with_event"], np.random.default_rng(run["seed"] + 3))
    declared = tuple(ctx.scen["declared_event_hours_s"]) if run["with_event"] else None
    first = (t_cfg["analysis_begin_s"] - t_cfg["sim_begin_s"]) // BUCKET_S - 1
    frac = row_frac if split == "train" else min(1.0, 2 * row_frac)
    rng = np.random.default_rng(run["seed"] + 4)
    out = {k: [] for k in ("X", "y", "base_tt", "rule_tt", "true_tt", "seg", "t", "h")}
    for b in range(T):
        obs.observe(b, np.nan_to_num(m["speed"][b].astype(float)), measured[b])
        if b < first:
            continue
        base = persistence(st, obs, b)
        keep_pair = rng.random(st.n) < frac
        for h in HORIZONS:
            tb = b + h
            if tb >= T:
                continue
            ok = keep_pair & st.in_sim & measured[tb] & ~closed[tb]
            if not ok.any():
                continue
            X = build_features(st, obs, b, h, sim_begin_s=t_cfg["sim_begin_s"], closed=closed, declared=declared,
                               event_estimate=est, base=base)
            target_s = t_cfg["sim_begin_s"] + tb * BUCKET_S + BUCKET_S / 2
            rule = event_rule(st, base[0], target_s, declared)
            idx = np.nonzero(ok)[0]
            out["X"].append(X[idx])
            out["y"].append(true_tt[tb, idx] - base[0][idx])
            out["base_tt"].append(base[0][idx])
            out["rule_tt"].append(rule[idx])
            out["true_tt"].append(true_tt[tb, idx])
            out["seg"].append(idx)
            out["t"].append(np.full(len(idx), b))
            out["h"].append(np.full(len(idx), h))
    arrs = {k: np.concatenate(v) for k, v in out.items()}
    ddir = ctx.dir / "dataset"
    np.savez_compressed(ddir / f"{run['run_id']}.npz", X=arrs["X"].astype(np.float32),
                        **{k: arrs[k].astype(np.float32 if k not in ("seg", "t", "h") else np.int16)
                           for k in arrs if k != "X"})
    return {"run_id": run["run_id"], "rows": int(len(arrs["y"])), "split": split}


def run(ev, row_frac: float) -> dict:
    ctx = Context(ev.key)
    split = assign_splits(ctx)
    ddir = ctx.dir / "dataset"
    ddir.mkdir(exist_ok=True)
    runs = [r for r in ctx.scen["runs"] if (ctx.dir / "runs" / r["run_id"] / "summary.json").exists()]
    (ddir / "splits.json").write_text(json.dumps({"seed": SPLIT_SEED, "families": split,
                                                   "runs": {r["run_id"]: split[r["family_id"]] for r in runs}}, indent=1))
    (ddir / "feature_schema.json").write_text(json.dumps({
        "features": FEATURES, "target": "simulated segment travel time at t+h minus persistence travel time [s]",
        "horizons_min": [h * 10 for h in HORIZONS], "bucket_s": BUCKET_S,
        "inputs_allowed": "observations <= origin bucket; published closure schedule; declared event hours; "
                          "noisy/missing declared event vehicle estimate; static road attributes",
        "inputs_forbidden": "future simulator states, realised arrival curve, exact generated demand, hidden scenario params",
    }, indent=1))
    workers = max(1, min(8, (os.cpu_count() or 2) // 2))
    with ProcessPoolExecutor(max_workers=workers) as ex:
        res = list(ex.map(build_run, [ev.key] * len(runs), runs, [split[r["family_id"]] for r in runs],
                          [row_frac] * len(runs)))
    by = {}
    for r in res:
        by.setdefault(r["split"], [0, 0])
        by[r["split"]][0] += 1
        by[r["split"]][1] += r["rows"]
    return {"runs": len(res), "by_split_runs_rows": by,
            "families_by_split": {s: sorted(f for f, v in split.items() if v == s) for s in ("train", "val", "test")}}
