"""Typed local shapes. These are ml-internal; the shared HTTP shape is proposed separately (see README) and goes
into contracts/ only through its own small PR."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field

import pandas as pd

LIVE = ("provisional", "accepted", "active")
TERMINAL = ("completed", "cancelled", "expired")


def to_epoch(t) -> float:
    if isinstance(t, (int, float)):
        return float(t)
    ts = pd.Timestamp(t)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    return ts.timestamp()


def iso(t: float | None) -> str | None:
    return None if t is None else pd.Timestamp(round(t, 3), unit="s", tz="UTC").isoformat(timespec="milliseconds")


def path_hash(road_ids) -> str:
    return hashlib.sha1("|".join(road_ids).encode()).hexdigest()[:12]


@dataclass
class RoadEntry:
    road: int
    entry: float            # epoch s (for the origin road: the departure time, vehicle already on it)
    exit: float
    f0: float = 0.0         # traversed fraction [f0, f1] of the road
    f1: float = 1.0


@dataclass
class TimedRoute:
    roads: list             # road indices in order
    entries: list           # RoadEntry per road
    depart: float
    arrive: float
    distance_m: float
    flags: list = field(default_factory=list)
    class_exposure_s: dict = field(default_factory=dict)

    @property
    def eta_s(self) -> float:
        return self.arrive - self.depart


@dataclass
class Candidate:
    candidate_id: str
    road_ids: list          # canonical road ids, in order
    timed: TimedRoute
    origin_fraction: float
    dest_fraction: float
    cells: dict = field(default_factory=dict)       # (resource index, bin) -> participating-entry weight
    features: dict = field(default_factory=dict)    # overlap, extra travel, class exposure, ...
    source: str = ""                                 # which search produced it

    @property
    def eta_s(self) -> float:
        return self.timed.eta_s


@dataclass
class RouteRequest:
    request_id: str
    origin: tuple            # (lon, lat)
    destination: tuple       # (lon, lat)
    depart_at: float         # epoch s UTC
    user_id: str | None = None
    reserve: bool = True     # False = plain preview: allocates nothing

    @classmethod
    def from_json(cls, d: dict, now: float) -> "RouteRequest":
        dep = d.get("depart_at")
        return cls(request_id=str(d["request_id"]), origin=tuple(map(float, d["origin"])),
                   destination=tuple(map(float, d["destination"])),
                   depart_at=max(now, to_epoch(dep)) if dep is not None else now,
                   user_id=d.get("user_id"), reserve=bool(d.get("reserve", True)))


@dataclass
class RequestCandidates:
    request: RouteRequest
    candidates: list         # Candidate, deterministic order (forecast ETA, then path hash)
    mask: list               # bool per candidate: valid to choose
    fastest_eta_s: float
    exclude_assignment: str | None = None   # reroute: this assignment's own remaining load is not "existing"
    forecast_version: str = ""              # snapshot the candidates were timed on; commit refuses a stale one


@dataclass
class SelectionContext:
    items: list              # RequestCandidates, in arrival order
    base_load: object        # callable (cell) -> fixed existing participating load
    cell_coef: object        # callable (cell) -> w / B^2
    lam: float
    forecast_version: str
    ledger_version: int
    deadline_ms: float
    seed: int
    tie_s: float = 0.5
    # read-only policy context (v1): what a learned selector may observe beyond the candidates. All of it is
    # available at serving time; nothing here comes from simulator internals.
    now: float = 0.0
    snapshot: object = None          # the ForecastSnapshot the candidates were timed on
    net: object = None               # RoadNetwork
    ledger_live: int = 0             # live assignments
    ledger_future_load: float = 0.0  # participating entries in the next 60 min of bins
    score_budget: object = None      # per-road allocation budget array (scoring.ConcentrationScore.budget)


@dataclass
class SelectionResult:
    choices: dict                                   # request_id -> candidate index
    policy: str
    policy_version: str
    runtime_ms: float = 0.0
    reasons: dict = field(default_factory=dict)     # request_id -> [reason codes]
    diagnostics: dict = field(default_factory=dict) # request_id -> {candidate_id: {...}}
    status: str = "ok"
    solver: dict = field(default_factory=dict)


@dataclass
class Assignment:
    assignment_id: str
    request_id: str
    version: int
    status: str
    created_at: float
    updated_at: float
    expires_at: float
    depart_at: float
    origin: list
    destination: list
    candidate_id: str
    route: list              # road ids
    schedule: list           # [[road_id, entry, exit, f0, f1], ...]
    progress_idx: int
    origin_fraction: float
    dest_fraction: float
    eta_s: float
    fastest_eta_s: float
    forecast_version: str
    network_version: str
    selector: str
    fallback_reason: str | None = None
    alternatives: dict = field(default_factory=dict)   # candidate_id -> {route, origin_fraction, dest_fraction}
    flags: list = field(default_factory=list)
    user_id: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Assignment":
        return cls(**d)
