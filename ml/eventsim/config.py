"""Paths, event definitions and shared constants.

Inputs are read as *data files* written by `ingest/` (never its Python modules), per AGENTS.md.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

ML_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = ML_DIR.parent
INGEST_DATA = Path(os.environ.get("INGEST_DATA_DIR", REPO_DIR / "ingest" / "data"))
RAW_DIR = INGEST_DATA / "raw"
TS_DIR = INGEST_DATA / "timeseries"

DATA_DIR = Path(os.environ.get("ML_DATA_DIR", ML_DIR / "data"))  # gitignored, rebuilt by the stages
REPORTS_DIR = ML_DIR / "reports"                                  # small, human-readable, committed

SF_TZ = ZoneInfo("America/Los_Angeles")
BUCKET_S = 600          # AGENTS.md: 10-minute UTC buckets
HORIZONS = (1, 3, 6)    # buckets ahead = 10, 30, 60 minutes

MPS_TO_MPH = 2.2369362920544
KMH_TO_MPH = 0.621371192
UNPOSTED_MPH = 25.0     # AGENTS.md: unposted SF street
FREEWAY_SENTINEL = 99   # DataSF speed_limits: state freeway, limit not posted by the city
HIGHWAY_DEFAULT_MPH = {"motorway": 55.0, "motorway_link": 35.0, "trunk": 40.0, "trunk_link": 30.0}
# AGENTS.md starting values until calibrated per road class
TILE_CONGESTION_RATIO = {"low": 0.1, "moderate": 0.4, "heavy": 0.65, "severe": 0.85}


@dataclass(frozen=True)
class EventDef:
    key: str
    case_num: str
    name: str
    # Public event hours. NOT in the closure records (permit windows include setup/teardown), so
    # they are a scenario assumption unless a verified schedule is added here.
    assumed_public_start_local: str
    assumed_public_end_local: str
    schedule_source: str
    patch_radius_m: float


EVENTS = {
    "castro": EventDef(
        key="castro", case_num="1534041", name="Castro Street Fair 2026",
        assumed_public_start_local="11:00", assumed_public_end_local="18:00",
        schedule_source="assumption: typical Castro Street Fair hours (not in DataSF records; unverified for 2026)",
        patch_radius_m=700.0,
    ),
    "folsom": EventDef(
        key="folsom", case_num="1532891", name="Folsom Street Fair 2026",
        assumed_public_start_local="11:00", assumed_public_end_local="18:00",
        schedule_source="assumption: typical Folsom Street Fair hours (not in DataSF records; unverified for 2026)",
        patch_radius_m=700.0,
    ),
}


def event_dir(key: str) -> Path:
    return DATA_DIR / key


def get_event(key: str) -> EventDef:
    if key not in EVENTS:
        raise SystemExit(f"unknown event {key!r}; known: {', '.join(EVENTS)}")
    return EVENTS[key]
