"""Run-tagged exports shaped like the Tiger tables (contracts/tiger_schema.sql), kept as separate files.

    python -m eventsim export --event castro [--runs f000_s0_ev ...]

data/<event>/export/simulation_metrics_<run>.csv   synthetic per-segment 10-min aggregates (never traffic_metrics)
data/<event>/export/prediction_metrics_<run>.csv   learned-model forecasts replayed on that run's observations

Loading them into Tiger / serving them to api/ needs an agreed contract change (see ml/README.md).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from .config import BUCKET_S, HORIZONS, MPS_TO_MPH
from .features import ObsModel, Static, build_features, declared_estimate, persistence, true_travel_time
from .simulate import Context
from .train import load_model


def utc_of(ctx: Context, local_s: float) -> datetime:
    day = datetime.fromisoformat(ctx.scen["local_day"])
    return (day + timedelta(seconds=local_s)).replace(tzinfo=timezone.utc) - timedelta(seconds=ctx.scen["time"]["utc_offset_s"])


def simulation_rows(ctx: Context, st: Static, run: dict) -> pd.DataFrame:
    m = np.load(ctx.dir / "runs" / run["run_id"] / "measurements.npz")
    tt, ok = true_travel_time(m["speed"].astype(float), m["sampledSeconds"].astype(float), st.length)
    rows = []
    for b in range(tt.shape[0]):
        t = utc_of(ctx, ctx.scen["time"]["sim_begin_s"] + b * BUCKET_S)
        for j in np.nonzero(ok[b] & st.in_sim)[0]:
            rows.append({"time": t.isoformat(), "run_id": run["run_id"], "scenario": run["family_id"],
                         "road_segment_id": ctx.seg_ids[j], "vehicle_count": int(np.nan_to_num(m["entered"][b, j])),
                         "avg_speed_mph": float(m["speed"][b, j]) * MPS_TO_MPH, "avg_delay_sec": float(tt[b, j] - st.ff_tt[j]),
                         "throughput_vph": float(np.nan_to_num(m["left"][b, j])) * 3600 / BUCKET_S})
    return pd.DataFrame(rows)


def prediction_rows(ctx: Context, st: Static, run: dict, model) -> pd.DataFrame:
    fam = ctx.fams[run["family_id"]]
    t_cfg = ctx.scen["time"]
    m = np.load(ctx.dir / "runs" / run["run_id"] / "measurements.npz")
    _, measured = true_travel_time(m["speed"].astype(float), m["sampledSeconds"].astype(float), st.length)
    closed = m["closed"].astype(bool)
    T = closed.shape[0]
    obs = ObsModel(st, fam["observation"], run["seed"] + 2, T)
    est = declared_estimate(fam, run["with_event"], np.random.default_rng(run["seed"] + 3))
    declared = tuple(ctx.scen["declared_event_hours_s"]) if run["with_event"] else None
    ev_id = ctx.patch["timed_restrictions"][0]["id"] if run["with_event"] else None
    rows = []
    for b in range(T):
        obs.observe(b, np.nan_to_num(m["speed"][b].astype(float)), measured[b])
        base = persistence(st, obs, b)
        issued = utc_of(ctx, t_cfg["sim_begin_s"] + (b + 1) * BUCKET_S)
        cur_mph = st.length / base[0] * MPS_TO_MPH
        for h in HORIZONS:
            X = build_features(st, obs, b, h, sim_begin_s=t_cfg["sim_begin_s"], closed=closed, declared=declared,
                               event_estimate=est, base=base)
            tt = model.predict_tt(X, base[0], np.arange(st.n))
            for j in np.nonzero(st.in_sim & ~closed[min(b + h, T - 1)])[0]:
                rows.append({"time": issued.isoformat(), "model_version": model.meta["model_version"], "event_id": ev_id,
                             "road_segment_id": ctx.seg_ids[j], "prediction_horizon_min": h * 10,
                             "current_speed_mph": float(cur_mph[j]), "predicted_speed_mph": float(st.length[j] / tt[j] * MPS_TO_MPH),
                             "predicted_delay_sec": float(tt[j] - st.ff_tt[j]), "predicted_demand": None,
                             "confidence": None, "synthetic_run_id": run["run_id"]})
    return pd.DataFrame(rows)


def run(ev, runs: list[str] | None) -> dict:
    ctx = Context(ev.key)
    st = Static(ctx)
    model = load_model(ev.key)
    chosen = [r for r in ctx.scen["runs"] if (runs and r["run_id"] in runs) or (not runs and r["with_event"])]
    chosen = chosen if runs else chosen[:1]
    out = ctx.dir / "export"
    out.mkdir(exist_ok=True)
    files = []
    for r in chosen:
        sim = simulation_rows(ctx, st, r)
        pred = prediction_rows(ctx, st, r, model)
        p1, p2 = out / f"simulation_metrics_{r['run_id']}.csv", out / f"prediction_metrics_{r['run_id']}.csv"
        sim.to_csv(p1, index=False)
        pred.to_csv(p2, index=False)
        files += [str(p1), str(p2)]
    return {"files": files}
