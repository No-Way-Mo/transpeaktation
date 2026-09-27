"""Versioned, diverse citywide scenario batches on the shared SF network (data generation only; no training).

    python -m eventsim.citywide_batch plan     --batch b2_bench [--families-per-event 1 --seeds 1 --seed 7]
    python -m eventsim.citywide_batch simulate --batch b2_bench --workers 6
    python -m eventsim.citywide_batch report   --batch b2_bench
    python -m eventsim.citywide_batch export   --batch b2_bench

Each batch lives in ml/data/sf_citywide/batches/<batch>/ and shares prepared/ and net/ with the v1 pilot (which
stays untouched at the dataset root). A batch's scenarios.json is frozen once written: a different plan needs a
new batch id.

Every family = one verified real event location + a sampled set of assumptions (time window, background demand
and OD structure, attendance-derived event vehicles, arrival/departure surge shape, ride-hail share, parking radius,
driver/routing parameters). Each family has `seeds` seed variants, and every seed variant is an event run plus a
no-event control with identical background trips. Other verified permitted closures active that day apply to both.
Family IDs and `family_group` (the event) are kept so related variants stay together in later splits.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import subprocess
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from .config import BUCKET_S, MPS_TO_MPH, REPORTS_DIR, SF_TZ
from .geo import LocalProj
from . import citywide as cw_mod, prepare as prep, simulate as sim, sumonet
from .citywide import KEY, ROOT, lane_junction, read, save, TELEPORT_RE

SCHEMA_VERSION = 2
TELEPORT_REVIEW_PER_1K = 10.0   # runs above this get quality_flag=review
UNFINISHED_REVIEW_SHARE = 0.001  # still driving at the end of the window; never-started/no-route trips: any = review
REVIEW = ROOT / "prepared" / f"{cw_mod.REVIEW_VERSION}.json"
DOWNTOWN = (-122.4000, 37.7880)   # Union Square-ish; used only for an OD weighting variant
WARMUP_S, DRAIN_S = 1800, 3600

# Verified event locations (closure_review_v2 status "verified"). Public hours are sourced only where a URL is
# given; otherwise they are an explicit assumption inside the permit window. Attendance ranges are assumptions.
EVENT_POOL = {
    "folsom": {"case_num": "1532891", "date": "2026-09-27", "hours": (11, 18), "profile": "weekend",
               "attendance": (60_000, 250_000), "schedule_source": cw_mod.EVENTS["folsom"]["source"]},
    "castro": {"case_num": "1534041", "date": "2026-10-04", "hours": (11, 18), "profile": "weekend",
               "attendance": (30_000, 90_000), "schedule_source": cw_mod.EVENTS["castro"]["source"]},
    "portola": {"case_num": "1583397", "date": "2026-09-27", "hours": (12, 22), "profile": "weekend",
                "attendance": (20_000, 50_000), "schedule_source": "assumption: inside permit window"},
    "sunday_streets_excelsior": {"case_num": "1516551", "date": "2026-10-18", "hours": (11, 16), "profile": "weekend",
                                 "attendance": (5_000, 25_000), "schedule_source": "assumption: inside permit window"},
    "bearrison": {"case_num": "1522782", "date": "2026-10-17", "hours": (11, 18), "profile": "weekend",
                  "attendance": (3_000, 15_000), "schedule_source": "assumption: inside permit window"},
    "halloween_cortland": {"case_num": "1551682", "date": "2026-10-31", "hours": (17, 20), "profile": "weekend",
                           "attendance": (2_000, 10_000), "schedule_source": "assumption: inside permit window"},
    "chinatown_night_market": {"case_num": "1472713", "date": "2026-10-09", "hours": (18, 23), "profile": "weekday",
                               "attendance": (3_000, 15_000), "schedule_source": "assumption: inside permit window"},
    "potrero_hill_festival": {"case_num": "1595585", "date": "2026-10-17", "hours": (10, 17), "profile": "weekend",
                              "attendance": (2_000, 10_000), "schedule_source": "assumption: inside permit window"},
}
# Sampler v3 event table. Hours and attendance come from a web review (2026-09-26); every value keeps its
# source URL and confidence. Attendance figures are mostly organisers' claims, not counts: they bound a sampled
# range, they don't fix the value. attendance_claim None = no published figure (the range is an assumption).
EVENT_POOL_V3 = {
    "folsom": {"case_num": "1532891", "date": "2026-09-27", "hours": (11, 18), "profile": "weekend",
               "hours_source": "https://www.folsomstreet.org/folsom-street-fair-1", "hours_confidence": "high",
               "attendance": (100_000, 275_000), "attendance_claim": 275_000,
               "attendance_source": "organiser '275K+' https://www.folsomstreet.org/sponsorship (2026)"},
    "castro": {"case_num": "1534041", "date": "2026-10-04", "hours": (11, 18), "profile": "weekend",
               "hours_source": "https://castrostreetfair.org/fair/", "hours_confidence": "high",
               "attendance": (50_000, 300_000), "attendance_claim": 300_000,
               "attendance_source": "300,000 (2007, low confidence) https://en.wikipedia.org/wiki/Castro_Street_Fair"},
    "portola": {"case_num": "1583397", "date": "2026-09-27", "hours": (13, 23), "profile": "weekend",
                "hours_source": "doors 13:00 https://portolamusicfestival.com/general-info/ (23:00 end: search snippet)",
                "hours_confidence": "medium", "attendance": (30_000, 42_000), "attendance_claim": 42_000,
                "attendance_source": "42,000/day (2024, Billboard/KTVU) https://en.wikipedia.org/wiki/Portola_Music_Festival"},
    "sunday_streets_excelsior": {"case_num": "1516551", "date": "2026-10-18", "hours": (11, 16), "profile": "weekend",
                                 "hours_source": "2025 hours https://www.sfmta.com/project-updates/sunday-streets-and-excelsior-festival",
                                 "hours_confidence": "medium", "attendance": (5_000, 25_000), "attendance_claim": None,
                                 "attendance_source": "not found (range is an assumption)"},
    "bearrison": {"case_num": "1522782", "date": "2026-10-17", "hours": (12, 18), "profile": "weekend",
                  "hours_source": "https://www.eventeny.com/events/bearrison-street-fair-29726/", "hours_confidence": "high",
                  "attendance": (5_000, 25_000), "attendance_claim": 25_000,
                  "attendance_source": "organiser '25K+' https://www.folsomstreet.org/sponsorship (2026)"},
    "halloween_cortland": {"case_num": "1551682", "date": "2026-10-31", "hours": (16.5, 20), "profile": "weekend",
                           "hours_source": "2025 hours https://halloweenoncortland.com/halloween-on-cortland-spooky-fun-awaits/",
                           "hours_confidence": "medium", "attendance": (2_000, 10_000), "attendance_claim": None,
                           "attendance_source": "not found (range is an assumption)"},
    "chinatown_night_market": {"case_num": "1472713", "date": "2026-10-09", "hours": (17, 21), "profile": "weekday",
                               "hours_source": "https://sf.funcheap.com/sfs-chinatown-night-market-returns-for-2026/",
                               "hours_confidence": "high", "attendance": (10_000, 15_000), "attendance_claim": 15_000,
                               "attendance_source": "10,000-15,000 per market (2025, NBC Bay Area) https://www.nbcbayarea.com/news/local/san-franciscos-chinatown-night-markets-return/3865616/"},
    "potrero_hill_festival": {"case_num": "1595585", "date": "2026-10-17", "hours": (10, 17), "profile": "weekend",
                              "hours_source": "https://potrerofestival.com/", "hours_confidence": "high",
                              "attendance": (2_000, 10_000), "attendance_claim": None,
                              "attendance_source": "not found (range is an assumption)"},
}
SAMPLER_VERSION = 3
# Load limits (v3). The b2 Folsom run (25,000 vehicles, +-38 min) overloaded SoMa. Attendees can't all park near
# an event and inflow is spread out: cap total event vehicles and the peak inflow/outflow rates.
MAX_EVENT_VEHICLES = 12_000
MAX_PEAK_ARRIVALS_VPH = 4_000
MAX_PEAK_DEPARTURES_VPH = 5_000
TRIGGER_RADIUS_M = 1500.0   # mid-run closures notify every edge within this radius (fixes onset leaks)

# Relative background demand by local hour (assumptions; no citywide OD or counts are available).
PROFILES = {
    "weekend": [.25, .2, .15, .12, .12, .18, .3, .45, .6, .75, .85, .95, 1, 1, 1, 1, .98, .95, .9, .8, .7, .6, .5, .35],
    "weekday": [.2, .15, .12, .1, .12, .3, .6, .95, 1, .8, .75, .8, .85, .85, .85, .95, 1, 1, .9, .75, .6, .5, .4, .3],
}
WINDOWS = ("arrival", "departure", "full")


def batch_dir(batch: str):
    if not re.fullmatch(r"[a-z0-9_]+", batch) or batch.startswith("v1"):
        raise SystemExit("batch ids are lowercase [a-z0-9_] and must not reuse the v1 pilot name")
    return ROOT / "batches" / batch


# ---------------------------------------------------------------- plan

def local_s(iso_utc: str, day: str) -> float:
    t = datetime.fromisoformat(iso_utc.replace("Z", "")).replace(tzinfo=timezone.utc).astimezone(SF_TZ)
    return (t - datetime.fromisoformat(day).replace(tzinfo=SF_TZ)).total_seconds()


def restrictions_on(review: dict, case: str, day: str, begin: float, end: float, source: str) -> list[dict]:
    """Accepted full-closure rows of one case that overlap [begin, end) on `day` (seconds from local midnight)."""
    out = []
    for r in review["rows"]:
        if r["case_num"] != case or r["decision"] != "accept":
            continue
        a, b = local_s(r["start_utc"], day), local_s(r["end_utc"], day)
        if a < end and b > begin and r["segment_ids"]:
            out.append({"id": r["objectid"], "case_num": case, "source": source, "segment_ids": r["segment_ids"],
                        "restriction": "full", "begin_s": a, "end_s": b, "review_reason": r["reason"],
                        "assumptions": r["match_flags"]})
    return out


HISTORY_MIN, AFTER_MIN = 60, 30   # long-horizon windows: history before the earliest issue; issue up to B + 30 min


def long_bounds(kind: str, hours: tuple[float, float], horizon_min: int) -> tuple[float, float]:
    """Unclamped simulation interval for forecasts issued in [B - horizon, B + 30 min] around one schedule boundary B
    (arrival: public start, departure: public end): demand covers 60 min of history before the earliest issue and
    the full horizon after the latest one; warmup before and the no-departure drain after it."""
    if kind not in ("arrival", "departure"):
        raise ValueError("long-horizon windows are per boundary: arrival or departure")
    b = hours[0] * 3600 if kind == "arrival" else hours[1] * 3600
    return b - (horizon_min + HISTORY_MIN) * 60 - WARMUP_S, b + (AFTER_MIN + horizon_min) * 60 + DRAIN_S


def window_for(kind: str, hours: tuple[int, int], horizon_min: int | None = None) -> tuple[int, int]:
    s, e = hours[0] * 3600, hours[1] * 3600
    if horizon_min:   # clamped to the event day (no cross-midnight runs); plan() records the truncation
        a, b = long_bounds(kind, hours, horizon_min)
    elif kind == "arrival":
        a, b = s - 2.5 * 3600, s + 2.5 * 3600
    elif kind == "departure":
        a, b = e - 2 * 3600, e + 3 * 3600
    else:
        a, b = s - 2 * 3600, e + 3 * 3600
    a, b = max(a, 0), min(b, 24 * 3600 - 600)
    return int(a // BUCKET_S * BUCKET_S), int(math.ceil(b / BUCKET_S) * BUCKET_S)


def demand_range() -> tuple[tuple[float, float], str]:
    """Background peak-demand range for sampler v3: +-25% around the calibrated level when calibration found demand
    identifiable, else the uncalibrated fallback range (recorded as such)."""
    path = ROOT / "calibration" / "calibration.json"
    if path.exists():
        c = read(path)
        if c.get("demand_identifiable") and c.get("calibrated_vph_peak"):
            v = float(c["calibrated_vph_peak"])
            return (0.75 * v, 1.25 * v), f"calibrated vs TomTom {c['day']} hours {c['hours']} (+-25%)"
        return tuple(c.get("fallback_vph_peak_range", (9_000, 16_000))), (
            f"uncalibrated: TomTom comparison on {c['day']} hours {c['hours']} could not identify demand")
    return (9_000.0, 16_000.0), "uncalibrated: no calibration run"


def sample_family(rng, event_key: str, window: str, idx: int, batch: str, version: int = 2,
                  bg_range: tuple[float, float] = (9_000, 16_000)) -> dict:
    ev = EVENT_POOL_V3[event_key] if version >= 3 else EVENT_POOL[event_key]
    low = rng.random() < 0.15
    att = float(rng.uniform(*ev["attendance"]))
    drive = float(rng.uniform(0.10, 0.35))
    occ = float(rng.uniform(1.3, 2.2))
    turnout = float(rng.uniform(0.6, 1.1)) if rng.random() > 0.08 else float(rng.uniform(0.1, 0.3))
    # Only part of the event's vehicles arrive/leave inside the simulated window; the rest is outside it.
    vehicles = int(min(att * drive / occ * turnout, 25_000 if version < 3 else MAX_EVENT_VEHICLES))
    fam = {
        "family_id": f"{batch}_{event_key}_{window}_f{idx:03d}", "family_group": event_key, "event_key": event_key,
        "case_num": ev["case_num"], "date": ev["date"], "window": window, "low_demand_control": bool(low),
        "background": {"vph_peak": float(rng.uniform(0.33 * bg_range[0], 0.66 * bg_range[0]) if low
                                          else rng.uniform(*bg_range)),
                       "profile": ev["profile"], "profile_jitter": float(rng.uniform(0.85, 1.15)),
                       "local_share": float(rng.uniform(0.4, 0.8)), "local_cell_m": float(rng.choice([1500, 2000, 3000])),
                       "od_weighting": str(rng.choice(["uniform", "arterial", "downtown"]))},
        "event": {"attendance_assumed": att, "drive_share": drive, "occupancy": occ, "turnout": turnout,
                  "vehicle_trips": vehicles, "ridehail_share": float(rng.uniform(0.15, 0.55)),
                  "arrival_offset_min": float(rng.uniform(-45, 120)), "arrival_sigma_min": float(rng.uniform(20, 90)),
                  "departure_surge_share": float(rng.uniform(0.4, 0.9)), "departure_surge_sigma_min": float(rng.uniform(10, 30)),
                  "parking_radius_m": [100.0, float(rng.uniform(500, 1500))], "origin_decay_km": float(rng.uniform(2, 8)),
                  "dwell_s": [20.0, float(rng.uniform(60, 150))]},
        "network": {"tls_cycle_s": 90},
        "driver": {"tau": float(rng.uniform(1.0, 1.4)), "sigma": float(rng.uniform(0.3, 0.6)),
                   "speed_dev": float(rng.uniform(0.05, 0.15)), "min_gap": float(rng.uniform(2.0, 3.0))},
        "routing": {"reroute_probability": float(rng.uniform(0.1, 0.5)), "reroute_period_s": int(rng.choice([120, 300]))},
        "sourced": {"event_location_and_closures": "DataSF permit rows accepted by closure_review_v2",
                    "public_hours": ev.get("schedule_source", ev.get("hours_source")), "event_date": "DataSF permit occurrence"},
        "assumed": ["attendance", "drive_share", "occupancy", "turnout", "background demand level/profile/OD",
                    "arrival/departure timing", "ride-hail share", "parking radius", "driver/routing parameters",
                    "90 s signal cycles", "missing lane counts"] + ([] if ev.get("schedule_source", "").startswith("http")
                                                                  or version >= 3 else ["public hours"]),
    }
    if version >= 3:
        e = fam["event"]
        # widen spreads so the peak inflow/outflow stays under the load limits (normal peak = n / (sigma * 2.5066))
        e["arrival_sigma_min"] = max(e["arrival_sigma_min"], 60 * vehicles / (MAX_PEAK_ARRIVALS_VPH * 2.5066))
        e["departure_surge_sigma_min"] = max(e["departure_surge_sigma_min"],
                                             60 * vehicles * e["departure_surge_share"] / (MAX_PEAK_DEPARTURES_VPH * 2.5066))
        e["ridehail_stop"] = "off_lane"
        fam["network"] = {"tls_cycle_s": 90, "signal_control": str(rng.choice(["static", "actuated"]))}
        fam["sourced"] = {"event_location_and_closures": "DataSF permit rows accepted by closure review v3",
                          "event_date": "DataSF permit occurrence",
                          "public_hours": f"{ev['hours_source']} ({ev['hours_confidence']} confidence)",
                          "attendance_range_anchor": ev["attendance_source"]}
        fam["assumed"] = (["attendance within the claim-anchored range" if ev["attendance_claim"] else "attendance range",
                           "drive_share", "occupancy", "turnout", "background demand profile/OD (level calibrated if "
                           "calibration.json exists)", "arrival/departure timing around public hours", "ride-hail share",
                           "parking radius", "driver/routing parameters", "signal control regime (fixed 90 s or actuated)",
                           "missing lane counts"] + ([] if ev["hours_confidence"] == "high" else ["public hours (2025 or partial)"]))
        fam["load_limits"] = {"max_event_vehicles": MAX_EVENT_VEHICLES, "max_peak_arrivals_vph": MAX_PEAK_ARRIVALS_VPH,
                              "max_peak_departures_vph": MAX_PEAK_DEPARTURES_VPH}
        # v3.1: event demand from the event's given attendance (API; attendance table until then), not a sampled
        # range; the only sampled conversions are mode share and occupancy. Background = trip requests.
        from .citywide_demand import attendance_for
        a_rec = attendance_for(ev["case_num"])
        att, turnout = float(a_rec["attendance"]), 1.0
        vehicles = int(min(att * drive / occ, MAX_EVENT_VEHICLES))
        e.update(attendance=att, attendance_is_estimate=bool(a_rec["is_estimate"]), attendance_method=a_rec["method"],
                 attendance_source=a_rec["source"], turnout=turnout, attendance_assumed=att, vehicle_trips=vehicles,
                 vehicles_before_cap=int(att * drive / occ))
        e["arrival_sigma_min"] = max(e["arrival_sigma_min"], 60 * vehicles / (MAX_PEAK_ARRIVALS_VPH * 2.5066))
        e["departure_surge_sigma_min"] = max(e["departure_surge_sigma_min"],
                                             60 * vehicles * e["departure_surge_share"] / (MAX_PEAK_DEPARTURES_VPH * 2.5066))
        fam["demand_mode"] = "requests"
        fam["assumed"] = [x for x in fam["assumed"] if not x.startswith("attendance")] + (
            ["attendance (category estimate)"] if a_rec["is_estimate"] else [])
    return fam


def plan(batch: str, families_per_event: int, seeds: int, seed: int, events: list[str] | None,
         windows: list[str] | None, version: int = SAMPLER_VERSION, requests: str | None = None,
         horizon_min: int | None = None) -> dict:
    out = batch_dir(batch)
    if (out / "scenarios.json").exists():
        raise SystemExit(f"{batch} already planned; scenarios are frozen. Use a new batch id.")
    review_path = latest_review() if version >= 3 else REVIEW
    review = read(review_path)
    status = {c["case_num"]: c["status"] for c in review["cases"]}
    pool = EVENT_POOL_V3 if version >= 3 else EVENT_POOL
    bg_range, bg_source = demand_range() if version >= 3 else ((9_000, 16_000), "assumption")
    if version >= 3 and not (ROOT / NET_V3 / "network.json").exists():
        raise SystemExit("sampler v3 needs network v3: run `python -m eventsim.citywide_batch network-v3`")
    rng = np.random.default_rng(seed)
    fams, runs = [], []
    chosen = events or list(pool)
    for ei, key in enumerate(chosen):
        ev = pool[key]
        if status.get(ev["case_num"]) != "verified":
            raise SystemExit(f"{key}: case {ev['case_num']} is not verified in {cw_mod.REVIEW_VERSION}")
        for j in range(families_per_event):
            ws = windows or WINDOWS
            # rotate the window types (the old (j + len(fams)) rotation never alternates with an even number of types)
            window = ws[(j + ei) % len(ws)] if horizon_min else ws[(j + len(fams)) % len(ws)]
            fam = sample_family(rng, key, window, len(fams), batch, version, bg_range)
            fam["background"]["demand_source"] = bg_source
            if requests:  # real client requests replace the synthetic background requests
                fam["background"].update(requests_path=str(requests), demand_source=f"client requests: {requests}")
            begin, end = window_for(window, ev["hours"], horizon_min)
            fam["time"] = {"sim_begin_s": begin, "analysis_begin_s": begin + WARMUP_S, "depart_end_s": end - DRAIN_S,
                           "sim_end_s": end, "warmup_s": WARMUP_S, "drain_s": DRAIN_S}
            if horizon_min:
                ra, rb = long_bounds(window, ev["hours"], horizon_min)
                fam["time"]["long_horizon"] = {
                    "horizon_min": horizon_min, "history_min": HISTORY_MIN, "issue_after_boundary_min": AFTER_MIN,
                    "requested_sim_begin_s": ra, "requested_sim_end_s": rb,
                    "truncated_at_day_end_s": max(0.0, rb - end), "truncated_at_day_start_s": max(0.0, begin - ra),
                    "note": "no cross-midnight runs: issue times whose horizon passes the day end have no windows"}
            fam["public_hours_s"] = [ev["hours"][0] * 3600, ev["hours"][1] * 3600]
            event_r = restrictions_on(review, ev["case_num"], ev["date"], begin, end, "event_permit")
            concurrent = []
            for c in review["cases"]:
                if c["status"] == "verified" and c["case_num"] != ev["case_num"]:
                    concurrent += restrictions_on(review, c["case_num"], ev["date"], begin, end, "concurrent_permit")
            fam["n_event_restrictions"], fam["n_concurrent_restrictions"] = len(event_r), len(concurrent)
            fams.append(fam)
            for k in range(seeds):
                s = int(rng.integers(1, 2**31 - 1))
                for active in (True, False):
                    runs.append({"run_id": f"{fam['family_id']}_s{k}_{'event' if active else 'control'}",
                                 "family_id": fam["family_id"], "family_group": key, "event_key": key,
                                 "with_event": active, "seed": s,
                                 "restrictions": (event_r if active else []) + concurrent})
    scen = {"schema_version": SCHEMA_VERSION if version < 3 else 3, "sampler_version": "3.1" if version >= 3 else version,
            "batch": batch, "demand": ("event attendance (event_attendance_v1 / API) + trip requests "
                                       "(synthetic stand-in unless --requests)") if version >= 3 else "v2 sampled",
            "network_dir": NET_V3 if version >= 3 else "net", "review_version": review_path.stem,
            "trigger_radius_m": TRIGGER_RADIUS_M if version >= 3 else None,
            "network_corrections": NETWORK_CORRECTIONS + ("; v3 network: parallel edges merged, closure segments never "
                                                          "absorbed, fixed/actuated signals" if version >= 3 else ""), "created_at": datetime.now(timezone.utc).isoformat(),
            "sampler_seed": seed, "horizon_min": horizon_min, "families": fams, "runs": runs,
            "profiles": PROFILES, "event_pool": pool,
            "provenance": "SYNTHETIC. Real network, verified permit closures and event dates; demand, attendance, "
                          "timing and behaviour are assumptions. Not observed traffic and not event ground truth."}
    save(out / "scenarios.json", scen)
    return {"batch": batch, "families": len(fams), "runs": len(runs),
            "windows": pd.Series([f["window"] for f in fams]).value_counts().to_dict()}


# ---------------------------------------------------------------- network corrections (batch schema v2)

NETWORK_CORRECTIONS = "v2: passenger cars disallowed on highway=busway and access=no (pilot v1 allowed them)"


def car_restricted() -> dict[str, str]:
    """Segments general traffic may not use: OSM highway=busway (Van Ness BRT, Transbay ramp) or access=no.
    The v1 pilot network let cars use them (~0.7% of simulated vehicle-km); v2 batches bake them out."""
    path = ROOT / "net" / "car_restricted_v2.json"
    if not path.exists():
        import xml.etree.ElementTree as ET
        ns = "{http://graphml.graphdrawing.org/xmlns}"
        root = ET.parse(cw_mod.RAW_DIR / "osm_drive_graph.graphml").getroot()
        keys = {k.get("id"): k.get("attr.name") for k in root.iter(ns + "key")}
        out = {}
        for e in root.iter(ns + "edge"):
            d = {keys[x.get("key")]: x.text for x in e.findall(ns + "data")}
            why = "highway=busway" if "busway" in str(d.get("highway")) else "access=no" if d.get("access") == "no" else None
            if why:
                out[f"{e.get('source')}-{e.get('target')}-{e.get('id') or '0'}"] = why
        save(path, out)
    return read(path)


# ---------------------------------------------------------------- network v3

NET_V3 = "net_v3"


def network_v3() -> dict:
    """Citywide network v3 (a new folder; net/ used by the pilot and b2_bench is untouched):
    * parallel OSM multi-edges (Ocean Ave etc.) merged into one edge with the lanes of both carriageways;
    * no accepted closure segment (closure review, any case) is absorbed into a merged junction, so every
      accepted closure piece can be closed and measured;
    * two signal regimes as a scenario assumption: fixed 90 s cycles and SUMO actuated (gap-based) control.
    """
    out = ROOT / NET_V3
    if (out / "network.json").exists():
        raise SystemExit(f"{NET_V3} exists; build a new version folder instead of overwriting")
    out.mkdir(parents=True, exist_ok=True)
    patch = read(ROOT / "prepared" / "patch.json")
    review = read(latest_review())
    protected = frozenset(x for r in review["rows"] if r["decision"] == "accept" for x in r["segment_ids"])
    info = sumonet.write_plain(patch, out, merge_parallel=True, protected=protected)
    nets = {"static_c90": sumonet.build(out, 90, "static"), "actuated": sumonet.build(out, 90, "actuated")}
    cw = sumonet.crosswalk(patch, nets["static_c90"], info["lanes"], info["clusters"], info["merged_parallel"])
    cw.to_csv(out / "crosswalk.csv", index=False)
    save(out / "routable_edges.json", sumonet.routable_edges(patch, nets["static_c90"]))
    absorbed = set(cw.road_segment_id[cw.absorbed_junction.notna()])
    loops = [s for s in cw.road_segment_id[(cw.n_sumo_edges == 0) & cw.absorbed_junction.isna()
                                           & cw.merged_parallel_into.isna()] if patch["segments"][s]["u"] == patch["segments"][s]["v"]]
    res = {"version": NET_V3, "review": review["version"], "canonical_segments": len(cw),
           "sumo_edges": int((cw.n_sumo_edges > 0).sum()), "merged_parallel": len(info["merged_parallel"]),
           "absorbed_junction_segments": len(absorbed), "accepted_closure_segments_absorbed": len(absorbed & protected),
           "self_loops_omitted": len(loops),
           "unexplained_missing": int(((cw.n_sumo_edges == 0) & cw.absorbed_junction.isna() & cw.merged_parallel_into.isna()).sum()) - len(loops),
           "signal_regimes": {k: v.name for k, v in nets.items()}, "junction_clusters": len(info["clusters"])}
    save(out / "network.json", res)
    return res


def latest_review():
    for v in ("closure_review_v3", cw_mod.REVIEW_VERSION):
        if (ROOT / "prepared" / f"{v}.json").exists():
            return ROOT / "prepared" / f"{v}.json"
    raise SystemExit("run `python -m eventsim.citywide review` first")


# ---------------------------------------------------------------- connectivity (cached once per network)

_ARCS_LOCK = threading.Lock()
_ARCS: dict = {}


def sumo_arcs(net_dir=None):
    """SUMO edge-to-edge connectivity of a network version, cached as JSON (sumolib parse is slow)."""
    net_dir = net_dir or ROOT / "net"
    with _ARCS_LOCK:
        if net_dir not in _ARCS:
            path = net_dir / "arcs_c90.json"
            if not path.exists():
                import sumolib
                net = sumolib.net.readNet(str(net_dir / "net_c90.net.xml"))
                save(path, [[e.getID(), o.getID()] for e in net.getEdges() for o in e.getOutgoing()])
            _ARCS[net_dir] = [tuple(a) for a in read(path)]
    return _ARCS[net_dir]


def od_edges(excluded: set[str], segments: dict, net_dir=None) -> list[str]:
    arcs = [(a, b) for a, b in sumo_arcs(net_dir) if a not in excluded and b not in excluded]
    return sorted(s for s in prep.largest_scc(arcs) if segments[s]["length_m"] >= 20)


# ---------------------------------------------------------------- demand

def _weights(mode: str, xy: np.ndarray, segments: dict, ids: list[str], proj: LocalProj) -> np.ndarray:
    if mode == "arterial":
        w = np.array([1.0 + segments[s]["rank"] for s in ids])
    elif mode == "downtown":
        d = np.linalg.norm(xy - proj.fwd([DOWNTOWN])[0], axis=1)
        w = 0.3 + np.exp(-d / 3000.0)
    else:
        w = np.ones(len(ids))
    return w / w.sum()


def batch_trips(ctx, fam: dict, run: dict, ids: list[str], parts=("background", "event")) -> list[dict]:
    """Background trips depend only on (family, seed, OD set): identical in the event run and its control."""
    seg = ctx.patch["segments"]
    proj = LocalProj(**ctx.patch["proj"])
    xy = proj.fwd(np.array([np.asarray(seg[s]["coords"]).mean(0) for s in ids]))
    bg, t = fam["background"], fam["time"]
    rng = np.random.default_rng(run["seed"])
    w = _weights(bg["od_weighting"], xy, seg, ids, proj)
    cells = defaultdict(list)
    cell_of = [tuple(np.floor(p / bg["local_cell_m"]).astype(int)) for p in xy]
    for i, c in enumerate(cell_of):
        cells[c].append(i)
    prof = PROFILES[bg["profile"]]
    trips = []
    for h0 in (range(t["sim_begin_s"] // 3600 * 3600, t["depart_end_s"], 3600) if "background" in parts else ()):
        a, b = max(h0, t["sim_begin_s"]), min(h0 + 3600, t["depart_end_s"])
        if b <= a:
            continue
        n = rng.poisson(bg["vph_peak"] * prof[(h0 // 3600) % 24] * bg["profile_jitter"] * (b - a) / 3600)
        origins = rng.choice(len(ids), size=n, p=w)
        for dep, o in zip(np.sort(rng.uniform(a, b, n)), origins):
            local = cells[cell_of[o]]
            d = int(rng.choice(local)) if rng.random() < bg["local_share"] and len(local) > 1 else int(rng.choice(len(ids), p=w))
            if d == o:
                d = (d + 1) % len(ids)
            trips.append({"id": f"bg{len(trips)}", "kind": "background", "depart": float(dep), "from": ids[o], "to": ids[d]})
    if not run["with_event"] or "event" not in parts:
        return trips
    ev = fam["event"]
    erng = np.random.default_rng(run["seed"] + 10_000)
    foot = np.vstack([np.asarray(seg[s]["coords"]) for r in run["restrictions"] if r["source"] == "event_permit"
                      for s in r["segment_ids"]])
    centre = proj.fwd(foot.mean(0))[0]
    dist = np.linalg.norm(xy - centre, axis=1)
    lo, hi = ev["parking_radius_m"]
    dests = np.flatnonzero((dist > lo) & (dist < hi))
    if not len(dests):
        raise ValueError(f"{run['run_id']}: no open parking/drop-off edges near the event")
    ow = np.exp(-dist / (ev["origin_decay_km"] * 1000))
    ow /= ow.sum()
    s0, e0 = fam["public_hours_s"]
    n = ev["vehicle_trips"]
    arr = erng.normal(s0 + ev["arrival_offset_min"] * 60, ev["arrival_sigma_min"] * 60, n)
    surge = erng.random(n) < ev["departure_surge_share"]
    # Non-surge leavers go any time between 30 min after arriving and 30 min after the end (late arrivals at
    # evening events can make that interval empty: they then leave at its upper bound).
    hi = e0 + 1800
    lo = np.minimum(np.maximum(arr + 1800, s0), hi)
    dep = np.where(surge, erng.normal(e0, ev["departure_surge_sigma_min"] * 60, n), lo + erng.random(n) * (hi - lo))
    ride = erng.random(n) < ev["ridehail_share"]
    for i in range(n):
        o, x = ids[int(erng.choice(len(ids), p=ow))], ids[int(erng.choice(dests))]
        back = ids[int(erng.choice(len(ids), p=ow))]
        dwell = float(erng.uniform(*ev["dwell_s"]))
        legs = ([("ridehail_dropoff", arr[i], o, back, x), ("ridehail_pickup", dep[i], o, back, x)] if ride[i]
                else [("event_arrival", arr[i], o, x, None), ("event_departure", dep[i], x, back, None)])
        for kind, when, a_, b_, stop in legs:
            if t["sim_begin_s"] <= when < t["depart_end_s"] and a_ != b_:
                tr = {"id": f"ev{kind[:3]}{kind[-3:]}{i}", "kind": kind, "depart": float(when), "from": a_, "to": b_}
                if stop and stop not in (a_, b_):
                    tr.update(stop=stop, dwell=dwell, off_lane=ev.get("ridehail_stop") == "off_lane")
                trips.append(tr)
    return sorted(trips, key=lambda x: x["depart"])


# ---------------------------------------------------------------- simulate

class BatchContext:
    def __init__(self, batch: str):
        self.dir = batch_dir(batch)
        self.scen = read(self.dir / "scenarios.json")
        # patch, crosswalk, lanes, in_sim of the batch's network version (pilot scenarios are not used)
        self.base = sim.Context(KEY, net_dir=self.scen.get("network_dir", "net"))
        self.fams = {f["family_id"]: f for f in self.scen["families"]}
        self._od, self._lock = {}, threading.Lock()
        self._snappers = {}
        self.restricted = car_restricted()
        cwx = pd.read_csv(self.base.net_dir / "crosswalk.csv")
        self.represented = ({r.road_segment_id: r.merged_parallel_into for r in cwx.itertuples()
                             if isinstance(r.merged_parallel_into, str)} if "merged_parallel_into" in cwx else {})
        self.trigger_radius = self.scen.get("trigger_radius_m")
        if self.trigger_radius:
            proj = LocalProj(**self.base.patch["proj"])
            segs = self.base.patch["segments"]
            self._mid = proj.fwd(np.array([np.asarray(segs[s]["coords"]).mean(0) for s in self.base.seg_ids]))
            self._sim_ids = np.asarray(self.base.seg_ids)[self.base.in_sim]
            self._sim_mid = self._mid[self.base.in_sim]

    def triggers(self, closed: set[str]) -> list[str]:
        """Every simulated edge within trigger_radius of a closed edge: a vehicle whose route crosses a newly closed
        edge is rerouted at its next edge entry, not only on the last approach (fixes the closure-onset leak)."""
        idx = self.base.idx
        pts = self._mid[[idx[s] for s in closed]]
        near = np.zeros(len(self._sim_ids), bool)
        for p in pts:
            near |= np.hypot(*(self._sim_mid - p).T) <= self.trigger_radius
        return self._sim_ids[near].tolist()

    def od(self, run):
        # exclude closed segments AND the edges that represent them (merged parallel carriageways), otherwise a
        # closed edge stays a trip endpoint (no-route trips, vehicles counted entering a closed road)
        excluded = frozenset(s for r in self.restrictions(run) if r["source"] == "concurrent_permit" for s in r["segment_ids"])
        excluded |= {s for r in self._event_restr(run) for s in r["segment_ids"]}
        excluded |= {self.represented.get(s, s) for s in excluded} | {s for s in run_ids(run) if s in self.represented}
        excluded |= set(self.restricted)
        key = hashlib.sha1(json.dumps(sorted(excluded)).encode()).hexdigest()[:12]
        with self._lock:
            if key not in self._od:
                path = self.dir / "od_cache" / f"{key}.json"
                if not path.exists():
                    save(path, od_edges(set(excluded), self.base.patch["segments"], self.base.net_dir))
                self._od[key] = read(path)
        return self._od[key]

    def restrictions(self, run) -> list[dict]:
        """Run restrictions with closures on merged parallel carriageways moved onto the edge that represents them
        (a closed street closes both carriageways, which network v3 carries on one edge)."""
        if not self.represented:
            return run["restrictions"]
        return [{**r, "segment_ids": sorted({self.represented.get(s, s) for s in r["segment_ids"]})}
                for r in run["restrictions"]]

    def snapper(self, ids: list[str]):
        from .citywide_demand import EdgeSnapper
        key = hashlib.sha1("|".join(ids).encode()).hexdigest()[:12]
        with self._lock:
            if key not in self._snappers:
                self._snappers[key] = EdgeSnapper(self.base.patch, ids)
        return self._snappers[key]

    def _event_restr(self, run):
        """OD for BOTH runs of a pair excludes the event closures, so background trips are identical."""
        twin = next((r for r in self.scen["runs"] if r["family_id"] == run["family_id"] and r["seed"] == run["seed"]
                     and r["with_event"]), None)  # calibration runs have no event twin
        if not twin:
            return []
        return [r for r in self.restrictions(twin) if r["source"] == "event_permit"]

    def view(self, fam):
        """A simulate.Context-compatible shallow copy carrying this family's clock (shared read-only data)."""
        c = copy.copy(self.base)
        c.scen = {**self.base.scen, "time": fam["time"]}
        c.trigger_fn = self.triggers if getattr(self, "trigger_radius", None) else None
        c.fams = self.fams  # simulate.extract looks families up here (the base context holds the pilot's)
        return c


def run_ids(run) -> set[str]:
    return {s for r in run["restrictions"] for s in r["segment_ids"]}


def _peak_rss(proc, stop: threading.Event, box: list):
    import psutil
    try:
        p = psutil.Process(proc.pid)
        while not stop.is_set():
            box[0] = max(box[0], p.memory_info().rss)
            stop.wait(2)
    except Exception:
        pass


def simulate_one(bc: BatchContext, run: dict, keep_raw: bool) -> dict:
    out = bc.dir / "runs" / run["run_id"]
    if (out / "summary.json").exists():
        return read(out / "summary.json")
    out.mkdir(parents=True, exist_ok=True)
    fam = bc.fams[run["family_id"]]
    ids = bc.od(run)
    demand_stats = None
    if fam.get("demand_mode") == "requests":
        trips, demand_stats = request_trips(bc, fam, run, ids, out)
    else:
        trips = batch_trips(bc.base, fam, run, ids)
    run = {**run, "restrictions": bc.restrictions(run)}
    ctx = bc.view(fam)
    sim.write_routes(trips, fam, out / "trips.rou.xml")
    static = sim.write_additional(ctx, run["restrictions"], out)
    static = sorted(set(static) | {(e, li) for e in bc.restricted if ctx.lanes.get(e) for li in range(ctx.lanes[e])})
    net = sim.variant_net(ctx, fam, static)
    cmd = sim.sumo_cmd(ctx, fam, run, net)
    i = cmd.index("--no-warnings")
    del cmd[i:i + 2]  # keep warnings: teleports are located per junction below
    t0 = time.time()
    with open(out / "sumo_warnings.log", "w", encoding="utf-8") as log:
        proc = subprocess.Popen(cmd, cwd=out, stdout=subprocess.DEVNULL, stderr=log)
        stop, box = threading.Event(), [0]
        th = threading.Thread(target=_peak_rss, args=(proc, stop, box), daemon=True)
        th.start()
        rc = proc.wait()
        stop.set()
    runtime = time.time() - t0
    stderr = (out / "sumo_warnings.log").read_text(encoding="utf-8", errors="replace")
    if rc:
        raise RuntimeError(f"{run['run_id']}: sumo exit {rc}: {stderr[-800:]}")
    tel = [{"vehicle": m.group(1), "reason": m.group(2) or m.group(3), "lane": m.group(4),
            "junction": lane_junction(m.group(4), bc.base.patch["segments"]), "time_s": float(m.group(5))}
           for m in TELEPORT_RE.finditer(stderr)]
    pd.DataFrame(tel, columns=["vehicle", "reason", "lane", "junction", "time_s"]).to_csv(out / "teleports.csv", index=False)
    result = sim.extract(ctx, run, out, trips, run["restrictions"], runtime, stderr, net)
    raw_mb = sum((out / f).stat().st_size for f in ("edgedata.xml", "tripinfo.xml") if (out / f).exists()) / 2**20
    if not keep_raw:
        for f in ("edgedata.xml", "tripinfo.xml"):
            try:
                (out / f).unlink(missing_ok=True)
            except PermissionError:
                pass
    (out / "sumo_warnings.log").write_text("\n".join(l for l in stderr.splitlines() if "Teleporting" not in l)[-200_000:],
                                           encoding="utf-8")
    result.update(batch=bc.scen["batch"], family_group=run["family_group"], event_key=run["event_key"],
                  window=fam["window"], local_day=fam["date"], time=fam["time"], synthetic=True,
                  dataset_status="synthetic_scenario_not_ground_truth", peak_rss_mb=round(box[0] / 2**20, 1),
                  raw_xml_mb=round(raw_mb, 1), raw_kept=keep_raw, demand=demand_stats,
                  disk_mb=round(sum(p.stat().st_size for p in out.iterdir()) / 2**20, 1),
                  n_event_restrictions=sum(r["source"] == "event_permit" for r in run["restrictions"]),
                  n_concurrent_restrictions=sum(r["source"] == "concurrent_permit" for r in run["restrictions"]))
    save(out / "summary.json", result)
    return result


def request_trips(bc: BatchContext, fam: dict, run: dict, ids: list[str], out) -> tuple[list[dict], dict]:
    """All demand as requests (lon/lat + time): background from client requests (file) or the synthetic stand-in,
    plus event requests from attendance. Saved as runs/<run>/requests.parquet, then snapped to roads."""
    from .citywide_demand import REQUEST_COLUMNS, edge_points, load_requests, synthetic_requests, trips_from_requests
    seg = bc.base.patch["segments"]
    proj = LocalProj(**bc.base.patch["proj"])
    bg = fam["background"]
    if bg.get("requests_path"):
        req = load_requests(bg["requests_path"], fam)
    else:
        xy = proj.fwd(np.array([np.asarray(seg[s]["coords"]).mean(0) for s in ids]))
        w = _weights(bg["od_weighting"], xy, seg, ids, proj)
        cell_of = [tuple(np.floor(p / bg["local_cell_m"]).astype(int)) for p in xy]
        cells = defaultdict(list)
        for i, c in enumerate(cell_of):
            cells[c].append(i)
        req = synthetic_requests(bc.base.patch, fam, run, ids, w, cell_of, cells, PROFILES[bg["profile"]])
    if run["with_event"]:  # event trips (attendance-derived) expressed as requests with real coordinates
        ev_trips = batch_trips(bc.base, fam, run, ids, parts=("event",))
        rng = np.random.default_rng(run["seed"] + 20_000)
        pos = {s: i for i, s in enumerate(ids)}
        rows = []
        for t in ev_trips:
            o, d = edge_points(bc.base.patch, ids, rng, np.array([pos[t["from"]], pos[t["to"]]]))
            st = edge_points(bc.base.patch, ids, rng, np.array([pos[t["stop"]]]))[0] if "stop" in t else (np.nan, np.nan)
            rows.append((t["id"], t["depart"], o[0], o[1], d[0], d[1], t["kind"], fam["case_num"], st[0], st[1],
                         t.get("dwell", np.nan)))
        req = pd.concat([req, pd.DataFrame(rows, columns=REQUEST_COLUMNS)], ignore_index=True)
    ev_legs = (len(ev_trips), 2 * fam["event"]["vehicle_trips"]) if run["with_event"] else None
    req = req.sort_values("depart_local_s").reset_index(drop=True)
    req.to_parquet(out / "requests.parquet", index=False)
    trips, stats = trips_from_requests(req, bc.snapper(ids))
    stats["by_kind"] = req.kind.value_counts().to_dict()
    if ev_legs:   # event legs outside [sim_begin, depart_end) are dropped: record the clipping
        stats["event_legs_in_window"], stats["event_legs_sampled"] = ev_legs
    return trips, stats


def simulate(batch: str, workers: int, only, keep_raw: bool) -> dict:
    bc = BatchContext(batch)
    runs = [r for r in bc.scen["runs"] if not only or r["run_id"] in only]
    # Largest (longest window) runs first so the pool isn't left waiting on one straggler.
    runs.sort(key=lambda r: -(bc.fams[r["family_id"]]["time"]["sim_end_s"] - bc.fams[r["family_id"]]["time"]["sim_begin_s"]))
    t0, done, failed = time.time(), [], []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(simulate_one, bc, r, keep_raw): r["run_id"] for r in runs}
        for f in as_completed(futs):
            try:
                s = f.result()
                done.append(s)
                print(f"{s['run_id']}: {s['runtime_s']}s trips={s['trips_generated']} unfinished={s['unfinished']} "
                      f"teleports={s['teleports'].get('total', 0)} rss={s['peak_rss_mb']}MB", flush=True)
            except Exception as e:
                failed.append({"run": futs[f], "error": str(e)[:600]})
                print(f"FAILED {futs[f]}: {str(e)[:300]}", flush=True)
    wall = time.time() - t0
    save(bc.dir / "simulate_log.json", {"workers": workers, "wall_s": wall, "completed": len(done), "failed": failed,
                                        "at": datetime.now(timezone.utc).isoformat()})
    return {"completed": len(done), "failed": failed, "wall_s": round(wall, 1)}


# ---------------------------------------------------------------- report / export

def segment_table(base) -> pd.DataFrame:
    patch = base.patch
    restricted = car_restricted()
    cw = pd.read_csv(base.net_dir / "crosswalk.csv").set_index("road_segment_id")
    rows = []
    for s in base.seg_ids:
        p = patch["segments"][s]
        in_sumo = bool(cw.loc[s, "n_sumo_edges"] > 0)
        absorbed = cw.loc[s, "absorbed_junction"]
        merged = cw.loc[s, "merged_parallel_into"] if "merged_parallel_into" in cw.columns else None
        rows.append({"road_segment_id": s, "cnn": p.get("cnn"), "name": p["name"], "highway": p["highway"],
                     "length_m": p["length_m"], "in_sumo": in_sumo,
                     "gap": "none" if in_sumo else ("absorbed_into_junction" if isinstance(absorbed, str)
                                                    else "merged_parallel" if isinstance(merged, str)
                                                    else "self_loop_omitted" if p["u"] == p["v"] else "unexplained"),
                     "represented_by": merged if isinstance(merged, str) else None,
                     "absorbed_junction": absorbed if isinstance(absorbed, str) else None,
                     "free_flow_speed_mph": p["fallback_free_flow_mph"], "free_flow_source": p["fallback_free_flow_source"],
                     "car_access": "no: " + restricted[s] if s in restricted else "yes",
                     "lanes_source": cw.loc[s, "lanes_source"], "tomtom_geometry": p["tomtom_line"],
                     "mapbox_geometry": p["mapbox_line"]})
    return pd.DataFrame(rows)


def export_run(bc: BatchContext, seg: pd.DataFrame, run: dict, out) -> dict | None:
    """One run's dense [bucket x segment] parquet (see export); None if the run has not finished."""
    src = bc.dir / "runs" / run["run_id"]
    path = out / f"sim_{run['run_id']}.parquet"
    if not (src / "summary.json").exists():
        return None
    ids = np.asarray(bc.base.seg_ids)
    ff = seg.free_flow_speed_mph.to_numpy()
    in_sumo = seg.in_sumo.to_numpy()
    batch = bc.scen["batch"]
    fam = bc.fams[run["family_id"]]
    t = fam["time"]
    with np.load(src / "measurements.npz") as m:
        speed, sampled = m["speed"].astype(float), np.nan_to_num(m["sampledSeconds"].astype(float))
        entered, left, closed = m["entered"], m["left"], m["closed"].astype(bool)
    T, E = speed.shape
    observed = (sampled > 0) & np.isfinite(speed)
    local = t["sim_begin_s"] + np.arange(T) * BUCKET_S
    midnight = datetime.fromisoformat(fam["date"]).replace(tzinfo=SF_TZ)
    utc = pd.to_datetime([(midnight + timedelta(seconds=int(s))).astimezone(timezone.utc) for s in local], utc=True)
    phase = np.where(local < t["analysis_begin_s"], "warmup", np.where(local >= t["depart_end_s"], "drain", "demand"))
    mph = np.where(observed, speed * MPS_TO_MPH, np.nan)
    df = pd.DataFrame({
        "time": np.repeat(utc, E), "road_segment_id": np.tile(ids, T),
        "speed_mph": mph.ravel(), "free_flow_speed_mph": np.tile(ff, T),
        "congestion_ratio": np.clip(1 - mph / ff[None, :], 0, 1).ravel(),
        "travel_time_s": np.where(observed, np.tile(seg.length_m.to_numpy(), (T, 1)) / np.maximum(speed, 0.1), np.nan).ravel(),
        "vehicles_entered": np.where(observed, np.nan_to_num(entered), 0).ravel().astype(np.int32),
        "throughput_vph": (np.nan_to_num(left) * 3600 / BUCKET_S).ravel().astype(np.float32),
        "sampled_vehicle_s": sampled.ravel().astype(np.float32),
        "observed": observed.ravel(), "closed": closed.ravel(), "in_sumo": np.tile(in_sumo, T),
        "phase": np.repeat(phase, E),
    })
    for k, v in {"run_id": run["run_id"], "family_id": run["family_id"], "family_group": run["family_group"],
                 "batch": batch, "with_event": run["with_event"], "seed": run["seed"], "window": fam["window"],
                 "synthetic": True, "source": "sumo_synthetic"}.items():
        df[k] = pd.Categorical([v] * len(df)) if isinstance(v, str) else v
    df.to_parquet(path, index=False, compression="zstd")
    return {"path": path.name, "rows": len(df), "observed_rows": int(observed.sum()),
            "mb": round(path.stat().st_size / 2**20, 2)}


def export(batch: str, only=None) -> dict:
    """Per run: dense [bucket x segment] parquet with explicit masks (observed, closed, in_sumo), phase labels and
    provenance. Empty buckets keep null speeds (observed=False); nothing is filled. Existing run files (e.g. exported
    on the simulation node right after the run) are kept and listed."""
    bc = BatchContext(batch)
    base = bc.base
    out = bc.dir / "export"
    out.mkdir(exist_ok=True)
    seg = segment_table(base)
    seg.to_parquet(out / "segments.parquet", index=False)
    files = []
    for run in bc.scen["runs"]:
        if only is not None and run["run_id"] not in only:
            continue
        path = out / f"sim_{run['run_id']}.parquet"
        if path.exists():
            files.append({"path": path.name, "mb": round(path.stat().st_size / 2**20, 2)})
            continue
        f = export_run(bc, seg, run, out)
        if f:
            files.append(f)
    manifest = {"batch": batch, "synthetic": True, "source": "sumo_synthetic",
                "status": "synthetic scenarios grounded in real roads and permits; not observed traffic, not event ground truth",
                "bucket_s": BUCKET_S, "time": "UTC bucket start", "speed_unit": "mph",
                "road_id": "canonical OSM u-v-key (Mongo road_segments.segment_id)",
                "columns": {"observed": "False = no vehicle sampled in the bucket: speed/ratio/travel time are null, never filled",
                            "closed": "segment fully closed by an enforced permit restriction in this bucket",
                            "in_sumo": "False = self-loop omitted or connector absorbed into a merged junction (see segments.parquet gap)",
                            "phase": "warmup | demand | drain (drain: no new departures; queues clearing)",
                            "congestion_ratio": "1 - speed/free_flow using the posted-limit fallback free flow (not measured)"},
                "separation": "offline files only; never load into observed traffic_metrics",
                "files": sorted(files, key=lambda f: f["path"]) + [
                    {"path": p.name, "mb": round(p.stat().st_size / 2**20, 2)} for p in [out / "segments.parquet"]]}
    flags = (pd.read_csv(bc.dir / "quality.csv").set_index("run_id").quality_flag.to_dict()
             if (bc.dir / "quality.csv").exists() else {})
    manifest["quality_flag_rule"] = (f"review if any not-inserted/no-route trip, > {UNFINISHED_REVIEW_SHARE:.1%} of trips still "
                                     f"driving at the end, > {TELEPORT_REVIEW_PER_1K:.0f} teleports per 1,000 trips, or "
                                     "steady-state closed-road entries (run `report` before `export`)")
    prev = read(out / "manifest.json")["files"] if (out / "manifest.json").exists() else []
    known = {f["path"] for f in manifest["files"]}
    manifest["files"] += [f for f in prev if f["path"] not in known]
    for f in manifest["files"]:
        rid = f["path"][4:-8] if f["path"].startswith("sim_") else None
        if rid:
            f["quality_flag"] = flags.get(rid, "unreported")
    save(out / "manifest.json", manifest)
    return {"exported": len(files), "dir": str(out)}


def report(batch: str) -> dict:
    bc = BatchContext(batch)
    rows, tel_all = [], []
    for run in bc.scen["runs"]:
        d = bc.dir / "runs" / run["run_id"]
        if not (d / "summary.json").exists():
            continue
        s = read(d / "summary.json")
        with np.load(d / "measurements.npz") as m:
            closed = m["closed"].astype(bool)
            ent = np.nan_to_num(m["entered"])
            steady = np.zeros_like(closed)
            steady[2:] = closed[2:] & closed[1:-1] & closed[:-2]
            seen = np.nan_to_num(m["sampledSeconds"]).sum(0) > 0
        tp = pd.read_csv(d / "teleports.csv")
        tp["run_id"] = run["run_id"]
        tel_all.append(tp)
        trips = pd.read_csv(d / "trips.csv")
        rows.append({"run_id": run["run_id"], "family_id": run["family_id"], "event": run["event_key"],
                     "window": s["window"], "with_event": run["with_event"],
                     "hours": (s["time"]["sim_end_s"] - s["time"]["sim_begin_s"]) / 3600,
                     "trips": s["trips_generated"], "unfinished": s["unfinished"],
                     "not_inserted": s["not_inserted_or_no_route"], "teleports": s["teleports"].get("total", 0),
                     "teleports_per_1k": round(1000 * s["teleports"].get("total", 0) / max(s["trips_generated"], 1), 2),
                     "closed_entries_steady": float(ent[steady].sum()),
                     "closed_entries_onset": float(ent[closed & ~steady].sum()),
                     "segments_with_traffic": int(seen.sum()),
                     "mean_trip_s": float(trips.loc[trips.arrived, "duration"].mean()),
                     "runtime_s": s["runtime_s"], "peak_rss_mb": s["peak_rss_mb"], "disk_mb": s["disk_mb"],
                     "raw_xml_mb": s["raw_xml_mb"], "event_restr": s["n_event_restrictions"],
                     "concurrent_restr": s["n_concurrent_restrictions"]})
    if not rows:
        raise SystemExit("no finished runs")
    df = pd.DataFrame(rows)
    # A run can finish yet be unusable: teleports delete queues. Flag instead of hiding or deleting.
    # trips still driving when the window closes are expected in small numbers (long trips departing late):
    # allow up to UNFINISHED_REVIEW_SHARE; trips that never started or had no route are always a failure
    bad = ((df.unfinished - df.not_inserted) / df.trips > UNFINISHED_REVIEW_SHARE) | (df.not_inserted > 0) | (
        df.teleports_per_1k > TELEPORT_REVIEW_PER_1K) | (df.closed_entries_steady > 0)
    df["quality_flag"] = np.where(bad, "review", "ok")
    df.to_csv(bc.dir / "quality.csv", index=False)
    tel = pd.concat(tel_all, ignore_index=True) if tel_all else pd.DataFrame()
    hot = tel.groupby("junction").agg(teleports=("vehicle", "size"), runs=("run_id", "nunique")).sort_values(
        "teleports", ascending=False) if len(tel) else pd.DataFrame()
    hot.to_csv(bc.dir / "teleport_hotspots.csv")
    log = read(bc.dir / "simulate_log.json") if (bc.dir / "simulate_log.json").exists() else {}
    res = {"runs": len(df), "planned": len(bc.scen["runs"]), "families": df.family_id.nunique(),
           "events": df.event.nunique(), "windows": df.drop_duplicates("family_id").window.value_counts().to_dict(),
           "quality_flags": df.quality_flag.value_counts().to_dict(),
           "review_runs": df.loc[df.quality_flag == "review", "run_id"].tolist(),
           "unfinished_total": int(df.unfinished.sum()), "not_inserted_total": int(df.not_inserted.sum()),
           "teleports_per_1k_median": float(df.teleports_per_1k.median()), "teleports_per_1k_max": float(df.teleports_per_1k.max()),
           "closed_entries_steady_total": float(df.closed_entries_steady.sum()),
           "runtime_s_per_sim_hour_median": float((df.runtime_s / df.hours).median()),
           "peak_rss_mb_max": float(df.peak_rss_mb.max()), "disk_mb_per_run_median": float(df.disk_mb.median()),
           "raw_xml_mb_per_sim_hour_median": float((df.raw_xml_mb / df.hours).median()),
           "wall_s": log.get("wall_s"), "workers": log.get("workers"),
           "top_teleport_junctions": hot.head(10).reset_index().to_dict("records") if len(hot) else []}
    save(bc.dir / "quality.json", res)
    return res


def _md_table(df: pd.DataFrame) -> list[str]:
    out = ["| " + " | ".join(map(str, df.columns)) + " |", "|" + "---|" * len(df.columns)]
    for r in df.itertuples(index=False):
        out.append("| " + " | ".join(f"{v:,.1f}" if isinstance(v, float) else str(v) for v in r) + " |")
    return out


def readiness(batch: str, target_families: int, target_seeds: int, workers: int) -> dict:
    """Data-readiness report: pilot + benchmark quality, coverage, scenario inventory, cost estimate, gaps."""
    bc = BatchContext(batch)
    q = report(batch)
    df = pd.read_csv(bc.dir / "quality.csv")
    pilot = read(ROOT / "coverage.json")
    review = read(REVIEW)
    diag = read(ROOT / "diagnostics" / "diagnostics.json") if (ROOT / "diagnostics" / "diagnostics.json").exists() else {}
    hot_pilot = pd.read_csv(ROOT / "diagnostics" / "teleport_hotspots.csv") if diag else pd.DataFrame()
    cw = pd.read_csv(bc.base.net_dir / "crosswalk.csv")
    segs = bc.base.patch["segments"]
    length = cw.set_index("road_segment_id").osm_length_m
    absorbed = set(cw.road_segment_id[cw.absorbed_junction.notna()])
    loops = [s for s in cw.road_segment_id[(cw.n_sumo_edges == 0) & cw.absorbed_junction.isna()] if segs[s]["u"] == segs[s]["v"]]
    accepted = {s for r in review["rows"] if r["decision"] == "accept" for s in r["segment_ids"]}
    restricted = car_restricted()
    parallel = pd.Series([s.rsplit("-", 1)[0] for s in segs]).value_counts()
    n_parallel = int((parallel > 1).sum())
    exp = read(bc.dir / "export" / "manifest.json") if (bc.dir / "export" / "manifest.json").exists() else {"files": []}
    exp_mb = [f["mb"] for f in exp["files"] if f["path"].startswith("sim_")]

    # cost model: runtime scales with simulated vehicle-hours ~ trips x hours; fit seconds per (trip x sim-hour)
    df["trip_hours"] = df.trips * df.hours
    k = float((df.runtime_s / df.trip_hours).median())
    fams = bc.scen["families"]
    mean_hours = float(np.mean([(f["time"]["sim_end_s"] - f["time"]["sim_begin_s"]) / 3600 for f in fams]))
    mean_trips = float(df.trips.mean())
    n_runs = target_families * target_seeds * 2
    cpu_h = n_runs * k * mean_trips * mean_hours / 3600
    per_run_disk = float(df.disk_mb.median()) + (float(np.median(exp_mb)) if exp_mb else 0)
    est = {"runs": n_runs, "cpu_hours": round(cpu_h, 1), "wall_hours_at_workers": round(cpu_h / workers, 1),
           "workers": workers, "peak_ram_gb": round(workers * float(df.peak_rss_mb.max()) / 1024, 1),
           "disk_gb": round(n_runs * per_run_disk / 1024, 1),
           "assumes": f"mean window {mean_hours:.1f} h, mean {mean_trips:,.0f} trips/run as in {batch}"}
    inv = pd.DataFrame([{"family": f["family_id"].replace(f"{batch}_", ""), "event": f["event_key"], "date": f["date"],
                         "window": f["window"],
                         "local": f"{f['time']['sim_begin_s'] / 3600:.1f}–{f['time']['sim_end_s'] / 3600:.1f} h",
                         "bg peak vph": round(f["background"]["vph_peak"]), "OD": f["background"]["od_weighting"],
                         "event veh": f["event"]["vehicle_trips"], "event closures": f["n_event_restrictions"],
                         "concurrent closures": f["n_concurrent_restrictions"],
                         "hours source": "sourced" if "public hours" not in f["assumed"] else "assumed"} for f in fams])
    qual = df[["run_id", "window", "hours", "trips", "unfinished", "not_inserted", "teleports", "teleports_per_1k",
               "closed_entries_steady", "closed_entries_onset", "segments_with_traffic", "runtime_s", "peak_rss_mb",
               "disk_mb", "quality_flag"]].copy()
    qual["run_id"] = qual.run_id.str.replace(f"{batch}_", "", regex=False)
    problems = []
    if q["unfinished_total"] or q["not_inserted_total"]:
        problems.append(f"{q['unfinished_total']} unfinished and {q['not_inserted_total']} not-inserted trips in {batch}")
    if q["closed_entries_steady_total"]:
        problems.append(f"{q['closed_entries_steady_total']:.0f} steady-state closed-road entries in {batch}")
    worst = df.sort_values("teleports_per_1k", ascending=False).iloc[0]
    lines = [
        "# Citywide synthetic traffic data: readiness report", "",
        f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} by "
        f"`python -m eventsim.citywide_batch readiness --batch {batch}`. **Data generation only: no model has been trained.**",
        "", "All traffic here is **synthetic** (SUMO), grounded in the real SF road graph, real permitted event closures and "
        "dates. Demand, attendance, timing, signal plans and driver behaviour are assumptions. Simulation does not "
        "create real event ground truth, and nothing here is observed traffic.", "",
        "## Verdict", "",
        f"- **Pilot (v1, 4 runs): complete.** 0 unfinished, 0 not-inserted and 0 closed-road entries in all four runs; "
        f"teleports 66–137 per run; roads with traffic in any run: {pilot['union_physical_street_length_coverage_pct']}% "
        "of physical street length.",
        f"- **Benchmark batch `{batch}` ({len(df)}/{len(bc.scen['runs'])} runs, {df.family_id.nunique()} families, "
        f"{df.event.nunique()} events):** unfinished {q['unfinished_total']}, not inserted {q['not_inserted_total']}, "
        f"steady-state closed-road entries {q['closed_entries_steady_total']:.0f}, teleports median "
        f"{q['teleports_per_1k_median']:.1f} per 1,000 trips (worst {worst.teleports_per_1k:.1f}: {worst.run_id}).",
        "- **Usable for:** relative event-vs-control effects on a shared citywide network (detours and spillover across "
        "neighbourhoods), with exact pairing of background trips. **Not usable as:** calibrated SF traffic levels, real "
        "event impacts, or ground truth.",
        f"- **Open problems:** {'; '.join(problems) if problems else 'none blocking in the benchmark'}; plus the network "
        "and demand gaps listed below.", "",
        "## Coverage", "",
        f"- Canonical graph: {len(segs):,} directed segments ({length.sum() / 1000:,.0f} km directed length).",
        f"- In SUMO: {int((cw.n_sumo_edges > 0).sum()):,}. Absorbed into merged junctions: {len(absorbed)} "
        f"({length[list(absorbed)].sum() / 1000:.1f} km, median {length[list(absorbed)].median():.0f} m). Self-loops omitted: "
        f"{len(loops)} ({length[loops].sum() / 1000:.1f} km). Unexplained omissions: "
        f"{int(((cw.n_sumo_edges == 0) & cw.absorbed_junction.isna()).sum()) - len(loops)}. All are flagged per segment "
        "(`segments.parquet` → `gap`), never filled.",
        f"- Roads carrying traffic: pilot union {pilot['union_directed_length_coverage_pct']}% of directed length; benchmark "
        f"median {df.segments_with_traffic.median():,.0f} segments per run. Empty buckets stay null (`observed=False`).",
        f"- Lanes: {int((cw.lanes_source != 'osm').sum()):,} segments use assumed lane counts; signal plans are all assumed "
        "(90 s cycles).", "",
        "## Event locations (closure review v2)", "",
        f"- 1,105 special-event closure rows / 184 permit cases. Row decisions: {review['row_decisions']}. Case status: "
        f"{review['case_status']}.",
        "- Accepted by rule, with reasons kept per row in `prepared/closure_review_v2.json` (the v1 matches are "
        "unchanged): undefined direction on all-lanes closures (both directions closed); unnamed links with ≥90% "
        "overlap; closures shorter than one same-named edge (whole edge closed, conservative, e.g. Folsom's Langton St "
        "row, which the v1 pilot left open); remainders with no drivable road under them (17th St at Castro = Jane "
        "Warner Plaza).",
        f"- {review['row_decisions'].get('needs_review', 0)} rows still need a human decision (mostly no same-named edge "
        "under the line). Cases with any such row are not used as scenario locations.",
        f"- {len(accepted & absorbed)} of {len(accepted)} accepted closure segments are junction connectors absorbed into "
        "merged junctions: those short pieces can't be closed or measured in SUMO (the adjacent closed blocks are).",
        "- Only `verified` cases are used. Public hours are sourced for Castro and Folsom; for the other events they are "
        "an assumption inside the permit window.", "",
        "## Quality problems investigated", "",
        f"- **Teleports (pilot, reproduced exactly with warnings on):** {diag.get('teleports', 'n/a')} teleports at "
        f"{diag.get('junctions', 'n/a')} junctions; top 10 junctions = {diag.get('top10_share_pct', 'n/a')}%; reasons "
        f"{diag.get('by_reason', {})}; at event closures: {diag.get('at_event_closures', 'n/a')}.",
    ]
    if len(hot_pilot):
        ocean = hot_pilot[(hot_pilot.lon.between(-122.4605, -122.4575)) & (hot_pilot.lat.between(37.7240, 37.7250))]
        lines.append(f"  - {int(ocean.teleports.sum())} of them ({100 * ocean.teleports.sum() / hot_pilot.teleports.sum():.0f}%) "
                     "are on one ~250 m stretch of Ocean Ave (Miramar/Faxon/Capitol), where OSM draws two parallel "
                     "carriageway edges between the same nodes (e.g. ways 679078809 and 1494530502). "
                     f"{n_parallel} such parallel pairs exist citywide. Not fixed yet; see gaps.")
    lines += [
        f"- **Bus-only roads open to cars (fixed for batches):** {len(restricted)} segments are `highway=busway` or "
        "`access=no` (Van Ness BRT, Transbay Bus Ramp, …). The v1 pilot let cars use them (~0.7% of simulated vehicle-km). "
        "Batch schema v2 bakes them out of each run's network (`segments.parquet` → `car_access`).",
        "- **Closure onset:** mid-simulation closures (SUMO rerouters) can still admit vehicles already committed past the "
        "last upstream trigger in the first 20 min; reported separately (`closed_entries_onset`).",
        f"- **Runs flagged `review` ({len(q['review_runs'])} of {len(df)}):** rule = any unfinished/not-inserted trip, "
        f"> {TELEPORT_REVIEW_PER_1K:.0f} teleports per 1,000 trips, or steady-state closed-road entries. Flagged runs are "
        "kept and exported with the flag in `quality.csv` and the export manifest; they are not deleted or re-planned."]
    for rid in q["review_runs"]:
        r = df.set_index("run_id").loc[rid]
        tp = pd.read_csv(bc.dir / "runs" / rid / "teleports.csv")
        why = []
        if r.unfinished or r.teleports_per_1k > TELEPORT_REVIEW_PER_1K:
            peak = (tp.time_s // 3600).value_counts().idxmax() if len(tp) else None
            fam = bc.fams[r.family_id]
            why.append(f"{r.teleports} teleports ({r.teleports_per_1k:.1f}/1k, peaking {peak:.0f}:00–{peak + 1:.0f}:00 local) and "
                       f"{r.unfinished} unfinished trips: event-induced overload. {fam['event']['vehicle_trips']:,} event "
                       f"vehicles (assumed attendance {fam['event']['attendance_assumed']:,.0f} × drive share "
                       f"{fam['event']['drive_share']:.2f}, at the cap) arrive with a ±{fam['event']['arrival_sigma_min']:.0f}-min "
                       "spread, and ride-hail stops block a travel lane. Teleports delete the queues, so this run is not "
                       "trustworthy even though it finished.")
        if r.closed_entries_steady:
            why.append(f"{r.closed_entries_steady:.0f} vehicles entered a closed edge 20–30 min after a mid-window closure "
                       "opened (queue already past the last rerouter trigger): the onset transient, slightly longer on a "
                       "busy arterial.")
        lines.append(f"  - `{rid}`: " + " ".join(why))
    lines += [
        f"- **Fixed during the benchmark:** evening events with late arrivals crashed departure sampling; batch runs used "
        "the pilot's family table when extracting. Both are covered by unit tests now.", "",
        f"## Scenario inventory: `{batch}`", "",
        "Each family: 1 seed variant here, each an event run + a no-event control with identical background trips. "
        "`family_id` and `family_group` (event) are kept for later grouped splits.", ""] + _md_table(inv) + [
        "", "Varied per family: event location/date (verified permits), time window (arrival / departure + 3 h recovery / "
        "full day), background peak demand, hourly profile (weekend/weekday), local-trip share and radius, OD weighting "
        "(uniform / arterial / downtown), attendance × drive share ÷ occupancy × turnout → event vehicles (capped at "
        "25,000), ride-hail share and curb dwell, arrival offset/spread, departure surge share/sharpness, parking radius, "
        "origin distance decay, driver and rerouting parameters, seed. Other verified closures active that day are "
        "applied to both runs of a pair.", "",
        "## Benchmark quality and cost", ""] + _md_table(qual) + [
        "", f"- Runtime ≈ {k * 1e3:.2f} ms per (trip × simulated hour); median "
        f"{q['runtime_s_per_sim_hour_median']:.0f} s per simulated hour. Peak memory per SUMO run: "
        f"{q['peak_rss_mb_max']:.0f} MB max. Disk per run (compact outputs, raw XML dropped): "
        f"{q['disk_mb_per_run_median']:.1f} MB + {np.median(exp_mb) if exp_mb else 0:.1f} MB parquet export. Raw XML would "
        f"add ~{q['raw_xml_mb_per_sim_hour_median']:.0f} MB per simulated hour.",
        f"- **Estimate for {target_families} families × {target_seeds} seeds × 2 = {est['runs']} runs:** "
        f"~{est['cpu_hours']} CPU-hours → ~{est['wall_hours_at_workers']} h wall at {workers} workers, "
        f"~{est['peak_ram_gb']} GB RAM, ~{est['disk_gb']} GB disk ({est['assumes']}). This machine has ~86 GB free disk, "
        "so keep raw XML off (`--keep-raw` only for diagnosis).", "",
        "## Normalized exports", "",
        f"- `ml/data/sf_citywide/batches/{batch}/export/sim_<run_id>.parquet`: dense segment × 10-min UTC bucket grid. "
        "Canonical `road_segment_id` (OSM u-v-key), `speed_mph`, `free_flow_speed_mph` (posted-limit fallback), "
        "`congestion_ratio`, `travel_time_s`, volumes, masks `observed` / `closed` / `in_sumo`, `phase` "
        "(warmup/demand/drain), and `run_id`, `family_id`, `family_group`, `batch`, `with_event`, `seed`, `window`, "
        "`synthetic=True`, `source=sumo_synthetic`.",
        f"- `…/{batch}/export/segments.parquet`: per-segment gaps, car access, free-flow and lane sources, provider "
        "geometry flags. `…/manifest.json`: schema notes.",
        "- v1 pilot: `ml/data/sf_citywide/export/simulation_observations_<run>.csv.gz` (observed rows only).",
        "- Scenario/provenance: `…/scenarios.json` (sourced vs assumed per family), `runs/<run>/summary.json`, "
        "`teleports.csv`, `quality.csv`, `teleport_hotspots.csv`.",
        "- Offline files only. They must never be loaded into observed `traffic_metrics`.", "",
        "## Remaining gaps before a large batch", "",
        f"1. Parallel OSM edges ({n_parallel} pairs), led by Ocean Ave: merge or drop the duplicate carriageway in a v3 "
        "network, then re-run the teleport diagnosis.",
        f"2. {review['row_decisions'].get('needs_review', 0)} closure rows need a human decision; "
        f"{review['case_status'].get('unverified', 0)} cases are unverified and {review['case_status'].get('partial', 0)} partial. "
        f"Only {len(EVENT_POOL)} of {review['case_status'].get('verified', 0)} verified cases are in the scenario pool "
        "(the rest are mostly small block parties and markets).",
        "3. Demand is uncalibrated: no citywide OD or counts. A first sanity check would compare simulated speeds with "
        "the TomTom/Mapbox polling at the same hour (units only, not calibration).",
        f"4. Public hours are assumed for {sum(not v['schedule_source'].startswith('http') for v in EVENT_POOL.values())} "
        f"of {len(EVENT_POOL)} events, and attendance is assumed for all of them.",
        "5. Event load: cap event vehicles per window well below 25,000, or spread arrivals, and give ride-hail stops "
        "off-lane curb space (SUMO `parkingArea` / `parking=\"true\"`) before the large batch. Keep `review`-flagged "
        "runs out of training by default.",
        "6. Signal timings (90 s everywhere) and 60% of lane counts are assumed.",
        "7. Closures on absorbed junction connectors aren't enforceable; mid-run closures have an onset transient.",
        "8. No real-event validation exists. Folsom 2026-09-27 is the first chance if the poller keeps running.", "",
        "Stop point: data generation and quality checks only. No windowing, split assignment or model training was done."]
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / "citywide_data_readiness.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    save(bc.dir / "cost_estimate.json", {**est, "sec_per_trip_hour": k})
    return {"report": str(path), "estimate": est, "problems": problems}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("stage", choices=["network-v3", "plan", "simulate", "report", "export", "readiness"])
    p.add_argument("--sampler-version", type=int, default=SAMPLER_VERSION, choices=[2, 3])
    p.add_argument("--batch")
    p.add_argument("--families-per-event", type=int, default=1)
    p.add_argument("--seeds", type=int, default=1)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--events", nargs="*", choices=list(EVENT_POOL_V3))
    p.add_argument("--windows", nargs="*", choices=list(WINDOWS))
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--only", nargs="*")
    p.add_argument("--keep-raw", action="store_true", help="keep edgedata/tripinfo XML (large)")
    p.add_argument("--requests", help="plan: client trip requests (parquet/csv) used as background demand")
    p.add_argument("--horizon-min", type=int, help="plan: long-horizon windows (issue times B-horizon..B+30 min)")
    p.add_argument("--target-families", type=int, default=100, help="readiness: size of the batch to cost")
    p.add_argument("--target-seeds", type=int, default=2)
    a = p.parse_args()
    t0 = time.time()
    if a.stage == "network-v3":
        r = network_v3()
    elif a.stage == "plan":
        r = plan(a.batch, a.families_per_event, a.seeds, a.seed, a.events, a.windows, a.sampler_version, a.requests,
                 a.horizon_min)
    elif a.stage == "simulate":
        r = simulate(a.batch, a.workers, a.only, a.keep_raw)
    elif a.stage == "export":
        r = export(a.batch)
    elif a.stage == "readiness":
        r = readiness(a.batch, a.target_families, a.target_seeds, a.workers)
    else:
        r = report(a.batch)
    print(json.dumps({"stage": a.stage, "batch": a.batch, "elapsed_s": round(time.time() - t0, 1), "result": r},
                     indent=1, default=str), flush=True)
    if isinstance(r, dict) and r.get("failed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
