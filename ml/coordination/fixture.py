"""Labeled development fixture in the road-forecast contract shape (forecast/CONTRACT_PROPOSAL.md).

NOT a forecast. The trained forecaster's export does not exist yet, so this produces a contract-shaped table from the
routing network only: free-flow travel time x a fixed road-class profile x a bump around scheduled closures x seeded
per-road noise. Every row has prediction_source="fixture", model_version="fixture:...", and every coordinated
response built on it carries the `fixture_forecast` degradation flag. Closure intervals come from a real scenario
run's scheduled restrictions (exact timestamps), so availability/closure handling is exercised on real data.

Replace with `python -m forecast predict ...` output as soon as one exists; the store validates both the same way.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .network import RoadNetwork

SF_TZ = ZoneInfo("America/Los_Angeles")
FIXTURE_VERSION = "fixture:class_profile_v0"
CLASS_FACTOR = {"motorway": 1.35, "trunk": 1.30, "primary": 1.35, "secondary": 1.30, "tertiary": 1.20,
                "residential": 1.10, "minor": 1.10}


def local_to_utc(date: str, sec: float) -> datetime:
    midnight = datetime.fromisoformat(date).replace(tzinfo=SF_TZ)
    return (midnight + timedelta(seconds=float(sec))).astimezone(timezone.utc)


def closures_from_run(scenarios_path, run_id: str) -> tuple[pd.DataFrame, dict]:
    """Scheduled restrictions of one simulated scenario run -> closure intervals (same recipe as
    forecast/events.run_context + forecast/predict.closure_table)."""
    sc = json.loads(Path(scenarios_path).read_text())
    run = next((r for r in sc["runs"] if r["run_id"] == run_id), None)
    if run is None:
        raise SystemExit(f"run {run_id} not in {scenarios_path}")
    fam = next(f for f in sc["families"] if f["family_id"] == run["family_id"])
    rows = [{"road_segment_id": s, "case_num": r["case_num"],
             "kind": "public_event" if r["source"] == "event_permit" else "permit", "restriction": r["restriction"],
             "closure_begin": pd.Timestamp(local_to_utc(fam["date"], r["begin_s"])),
             "closure_end": pd.Timestamp(local_to_utc(fam["date"], r["end_s"]))}
            for r in run["restrictions"] for s in r["segment_ids"]]
    info = {"run_id": run_id, "family_id": fam["family_id"], "date": fam["date"], "event_key": fam.get("event_key"),
            "public_hours_utc": [local_to_utc(fam["date"], s).isoformat() for s in fam.get("public_hours_s", [])]}
    return pd.DataFrame(rows, columns=["road_segment_id", "case_num", "kind", "restriction", "closure_begin",
                                       "closure_end"]), info


def _cover(closures: pd.DataFrame, net: RoadNetwork, starts: np.ndarray, B: float) -> np.ndarray:
    out = np.zeros((len(starts), net.n))
    for r in closures[closures.restriction == "full"].itertuples():
        j = net.pos.get(r.road_segment_id)
        if j is None:
            continue
        b, e = r.closure_begin.timestamp(), r.closure_end.timestamp()
        out[:, j] = np.maximum(out[:, j], np.clip((np.minimum(starts + B, e) - np.maximum(starts, b)) / B, 0, 1))
    return out


def build(net: RoadNetwork, issued_at, closures: pd.DataFrame | None = None, seed: int = 0, bucket_min: int = 10,
          horizons: int = 6, bump: float = 0.6, bump_radius_m: float = 400.0) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    t = pd.Timestamp(issued_at)
    t = (t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")).floor(f"{bucket_min}min")
    closures = closures if closures is not None else pd.DataFrame(
        columns=["road_segment_id", "case_num", "kind", "restriction", "closure_begin", "closure_end"])
    B = bucket_min * 60.0
    starts = t.timestamp() + B * np.arange(horizons)
    cover = _cover(closures, net, starts, B)
    rng = np.random.default_rng(seed)
    noise = np.exp(rng.normal(0.0, 0.08, net.n))
    base = np.array([CLASS_FACTOR.get(h, 1.1) for h in net.hw]) * noise
    mid = np.array([xy.mean(0) if len(xy) else [0, 0] for xy in net.geom_xy])

    # congestion bump around roads under a full closure during (or within 30 min before) each bucket
    bumpk = np.zeros((horizons, net.n))
    if len(closures):
        from scipy.spatial import cKDTree
        cb = closures.closure_begin.map(lambda x: x.timestamp())
        ce = closures.closure_end.map(lambda x: x.timestamp())
        for k in range(horizons):
            act = closures[(closures.restriction == "full") & (cb < starts[k] + B + 1800) & (ce > starts[k])]
            ids = [net.pos[s] for s in act.road_segment_id.unique() if s in net.pos]
            if not ids:
                continue
            d = cKDTree(mid[ids]).query(mid, k=1)[0]
            bumpk[k] = bump * np.exp(-d / bump_radius_m)

    avail_static = net.static_availability
    rows = []
    for k in range(horizons):
        tt = net.ff_tt_s * base * (1 + 0.04 * k) * (1 + bumpk[k])
        avail = np.where(avail_static == "alias", "open", avail_static).astype(object)
        reason = np.full(net.n, "none", object)
        reason[avail_static == "restricted"] = "no_passenger_access"
        un = avail_static == "unavailable"
        reason[un] = [f"not_modelled:{g}" for g in net.gap[un]]
        src = np.where(avail_static == "open", "fixture", "none").astype(object)
        rep = np.full(net.n, None, object)
        al = np.flatnonzero(avail_static == "alias")
        tt = tt.copy()
        for i in al:
            j = net.resource[i]
            if avail_static[j] == "open":
                tt[i] = tt[j]
                src[i] = "representative_road"
                rep[i] = net.ids[j]
                reason[i] = "merged_parallel"
            else:
                avail[i] = "unavailable"
                reason[i] = "not_modelled:merged_parallel"
        full = cover[k] >= 1.0
        part = (cover[k] > 0) & ~full
        m_full = full & (avail == "open")
        avail[m_full] = "closed"
        reason[m_full] = "scheduled_closure"
        m_part = part & (avail == "open")
        avail[m_part] = "restricted"
        reason[m_part] = "partial_closure_see_closures_table"
        has = (src != "none") & np.isin(avail, ["open", "restricted"]) & (reason != "no_passenger_access")
        ttk = np.where(has, tt, np.nan)
        spd = np.where(has, net.length_m / np.maximum(ttk, 1e-6) * 2.2369362920544, np.nan)
        cong = np.where(has, np.clip(1 - spd / net.free_flow_mph, 0, 1), np.nan)
        rows.append(pd.DataFrame({
            "road_segment_id": net.ids, "issued_at": t, "valid_from": t + pd.Timedelta(seconds=B * k),
            "valid_to": t + pd.Timedelta(seconds=B * (k + 1)), "horizon_min": (k + 1) * bucket_min,
            "predicted_travel_time_sec": ttk, "predicted_speed_mph": spd, "predicted_congestion_ratio": cong,
            "availability": avail, "restriction_reason": reason, "prediction_source": np.where(has, src, "none"),
            "represented_by": rep}))
    df = pd.concat(rows, ignore_index=True)
    df["model_version"] = FIXTURE_VERSION
    df["network_version"] = net.version
    df["dataset_id"] = "none"
    df["training_source"] = "none:fixture"
    df["input_source"] = "fixture"
    df["synthetic_training"] = False
    meta = {"FIXTURE": "development fixture, not a forecast: free-flow x class profile x closure bump x noise",
            "fixture_version": FIXTURE_VERSION, "seed": seed, "issued_at": t.isoformat(),
            "class_factor": CLASS_FACTOR, "horizon_growth_per_step": 0.04, "bump": bump,
            "bump_radius_m": bump_radius_m, "noise_sigma_log": 0.08,
            "network_version": net.version, "rows": len(df),
            "availability_counts": df.availability.value_counts().to_dict()}
    return df, closures, meta


def write(df: pd.DataFrame, closures: pd.DataFrame, meta: dict, output) -> Path:
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    closures.to_parquet(out.with_suffix(".closures.parquet"), index=False)
    out.with_suffix(".meta.json").write_text(json.dumps(meta, indent=1, default=str))
    return out
