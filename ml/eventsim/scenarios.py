"""Stage 3a: sample scenario configurations.

    python -m eventsim scenarios --event castro --families 12 --seeds 2

A *family* fixes the closure variant and parameter setup; each family has `seeds` seed variants,
and every seed variant has an event run and a no-event control that share background demand.
Family members always stay in one split (train.py).

Everything below is a scenario assumption varied within ranges, not a fact about the real event.
Sourced inputs (closure edges and windows, road network) come from prepare.py.

Output: ml/data/<event>/scenarios.json
"""
from __future__ import annotations

import json
from datetime import datetime

import numpy as np

from .config import SF_TZ, event_dir
from .sumonet import CYCLES

SIM_BEGIN = 9 * 3600 + 1800     # 09:30 local; 30 min warm-up
ANALYSIS_BEGIN = 10 * 3600      # 10:00 local, first bucket used for data
DEPART_END = 20 * 3600 + 1800   # last departure 20:30
SIM_END = 21 * 3600 + 1800      # 21:30: one hour to finish; still running = unfinished

# Hypothetical closure variants (clearly labelled); "permit" is the real permitted footprint.
CLOSURE_VARIANTS = {"permit": 0.6, "permit_market_open": 0.2, "permit_market_one_lane": 0.2}

# Weekend background demand shape by local hour (assumption; no measured daytime demand exists).
HOURLY_SHAPE = {9: 0.7, 10: 0.8, 11: 0.9, 12: 1.0, 13: 1.0, 14: 1.0, 15: 1.0, 16: 1.05, 17: 1.05,
                18: 0.95, 19: 0.85, 20: 0.75, 21: 0.6}


def local_seconds(iso_utc: str, day: str) -> float:
    t = datetime.fromisoformat(iso_utc.replace("Z", "+00:00")).astimezone(SF_TZ)
    midnight = datetime.fromisoformat(day).replace(tzinfo=SF_TZ)
    return (t - midnight).total_seconds()


def sample_family(rng: np.random.Generator, fid: int) -> dict:
    low_demand = rng.random() < 0.12
    arr_mu = rng.uniform(11.5, 14.0) * 3600
    ev_trips = int(rng.uniform(300, 3000))
    turnout = 1.0
    if rng.random() < 0.08:  # low-turnout / partially cancelled event
        turnout = rng.uniform(0.1, 0.35)
    variant = rng.choice(list(CLOSURE_VARIANTS), p=list(CLOSURE_VARIANTS.values()))
    fam = {
        "family_id": f"f{fid:03d}",
        "closure_variant": str(variant),
        "background_vph": float(rng.uniform(250, 450) if low_demand else rng.uniform(700, 1400)),
        "through_share": float(rng.uniform(0.45, 0.7)),
        "low_demand_control": bool(low_demand),
        "event": {
            "vehicle_trips": ev_trips,                 # arriving event vehicles (directly varied; no attendance data)
            "turnout_factor": float(turnout),
            "ridehail_share": float(rng.uniform(0.15, 0.55)),
            "arrival_mu_s": float(arr_mu), "arrival_sigma_s": float(rng.uniform(30, 90) * 60),
            "departure_mu_s": float(rng.uniform(17.0, 18.75) * 3600), "departure_sigma_s": float(rng.uniform(20, 60) * 60),
            "dwell_s": [float(rng.uniform(20, 45)), float(rng.uniform(60, 150))],
            "dest_radius_m": [50.0, float(rng.uniform(350, 650))],
        },
        "network": {"tls_cycle_s": int(rng.choice(CYCLES))},
        "driver": {"tau": float(rng.uniform(1.0, 1.4)), "sigma": float(rng.uniform(0.3, 0.6)),
                   "speed_dev": float(rng.uniform(0.05, 0.15)), "min_gap": float(rng.uniform(2.0, 3.0))},
        "routing": {"reroute_probability": float(rng.uniform(0.1, 0.6)),
                    "reroute_period_s": int(rng.choice([60, 120, 300]))},
        "observation": {  # model-visible observation corruption (applied in dataset.py / replay.py)
            "speed_noise_sigma": float(rng.uniform(0.05, 0.2)),
            "tomtom_missing": float(rng.uniform(0.05, 0.3)),
            "stale_prob": float(rng.uniform(0.0, 0.2)),
            "event_estimate_sigma": float(rng.uniform(0.2, 0.5)),
            "event_estimate_missing": 0.2,
        },
    }
    # Harder test families: largest events and a closure/timing combination never trained on.
    fam["hard_test"] = bool(ev_trips * turnout > 2600 or (variant == "permit_market_one_lane" and arr_mu > 13.25 * 3600))
    return fam


def run(ev, families: int, seeds: int, seed: int) -> dict:
    d = event_dir(ev.key)
    event = json.loads((d / "prepared" / "event.json").read_text(encoding="utf-8"))
    patch = json.loads((d / "prepared" / "patch.json").read_text(encoding="utf-8"))
    day = event["local_day"]
    rng = np.random.default_rng(seed)
    pub = [datetime.fromisoformat(x) for x in event["assumptions"]["public_hours_local"]]
    midnight = datetime.fromisoformat(day).replace(tzinfo=SF_TZ)
    declared = [(p - midnight).total_seconds() for p in pub]
    restrictions = [{**t, "begin_s": local_seconds(t["start_utc"], day), "end_s": local_seconds(t["end_utc"], day)}
                    for t in patch["timed_restrictions"]]
    runs = []
    fams = [sample_family(rng, i) for i in range(families)]
    for fam in fams:
        for k in range(seeds):
            s = int(rng.integers(1, 2**31 - 1))
            for with_event in (True, False):
                rid = f"{fam['family_id']}_s{k}_{'ev' if with_event else 'ctl'}"
                runs.append({"run_id": rid, "family_id": fam["family_id"], "seed": s, "with_event": with_event})
    out = {
        "event_key": ev.key, "local_day": day, "sampler_seed": seed,
        "time": {"sim_begin_s": SIM_BEGIN, "analysis_begin_s": ANALYSIS_BEGIN, "depart_end_s": DEPART_END,
                 "sim_end_s": SIM_END, "utc_offset_s": int(midnight.utcoffset().total_seconds())},
        "declared_event_hours_s": declared,
        "declared_source": event["assumptions"]["public_hours_source"],
        "restrictions": restrictions,
        "hourly_shape": HOURLY_SHAPE,
        "families": fams, "runs": runs,
        "provenance": "families/runs are scenario assumptions; restrictions are sourced (DataSF permits)",
    }
    (d / "scenarios.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return {"families": len(fams), "runs": len(runs), "hard_test_families": sum(f["hard_test"] for f in fams)}
