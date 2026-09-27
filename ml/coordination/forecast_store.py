"""Validated, immutable forecast snapshots and an atomically swapped store.

Input = the road forecast export described in forecast/CONTRACT_PROPOSAL.md (one row per road x issue time x
horizon) plus its `.closures.parquet` companion. Horizon 10k covers [issued_at + 10(k-1) min, issued_at + 10k min),
UTC. A replacement that fails validation is refused and the last good snapshot keeps serving.

Missing forecasts never mean free flow: a road without a usable row for an interval cannot be entered in it.
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .network import RoadNetwork

REQUIRED = ["road_segment_id", "issued_at", "valid_from", "valid_to", "horizon_min", "predicted_travel_time_sec",
            "predicted_speed_mph", "predicted_congestion_ratio", "availability", "restriction_reason",
            "prediction_source", "represented_by", "model_version", "network_version"]
PROVENANCE = ["dataset_id", "training_source", "input_source", "synthetic_training"]
AVAILABILITY = {"open", "closed", "restricted", "unavailable"}
# `fixture` is not a contract value: it marks a labeled development forecast (see fixture.py) and every response
# built on it carries the `fixture_forecast` degradation flag.
SOURCES = {"model", "representative_road", "none", "fixture"}
PARTIAL = "partial_closure_see_closures_table"
# closure semantics: "full" blocks entry AND requires clearance (a vehicle may not be on the road during the
# interval, so entry is refused if the closure starts before the vehicle would leave). Unknown kinds are treated
# the same way (conservative). Nothing else is known in current exports.
CLEARANCE_RESTRICTIONS = {"full"}


class ForecastInvalid(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems[:8]) + (f" (+{len(problems) - 8} more)" if len(problems) > 8 else ""))
        self.problems = problems


def _utc(s) -> pd.Timestamp:
    t = pd.Timestamp(s)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


@dataclass(frozen=True, eq=False)
class ForecastSnapshot:
    version: str                 # content hash; changes whenever anything routing-relevant changes
    issued_at: float             # epoch seconds UTC
    bucket_s: float
    H: int
    tt: np.ndarray               # [R, H] predicted travel time; NaN where not enterable
    cong: np.ndarray             # [R, H] predicted congestion ratio (context only, never a cost)
    ok: np.ndarray               # [R, H] enterable in this interval (subject to exact closure intervals)
    source: np.ndarray           # [R, H] prediction_source
    closures: dict               # road index -> tuple of (begin, end, restriction)
    model_version: str
    network_version: str
    provenance: dict
    coverage: dict
    fixture: bool

    @property
    def horizon_end(self) -> float:
        return self.issued_at + self.H * self.bucket_s

    def bucket(self, t: float) -> int:
        return int((t - self.issued_at) // self.bucket_s)

    def blocked(self, i: int, entry: float, exit_: float) -> str | None:
        """Closure that forbids entering road i at `entry` and staying until `exit_`, else None."""
        for b, e, kind in self.closures.get(i, ()):
            if kind in CLEARANCE_RESTRICTIONS or kind not in ("partial", "lane"):
                if b < exit_ and entry < e:
                    return kind
        return None

    def age_min(self, now: float) -> float:
        return (now - self.issued_at) / 60.0

    def summary(self) -> dict:
        return {"forecast_version": self.version, "issued_at": pd.Timestamp(self.issued_at, unit="s", tz="UTC").isoformat(),
                "valid_until": pd.Timestamp(self.horizon_end, unit="s", tz="UTC").isoformat(),
                "model_version": self.model_version, "network_version": self.network_version,
                "fixture": self.fixture,
                **{k: v for k, v in self.provenance.items() if k not in ("meta", "source_file")},
                **({"label": self.provenance.get("meta", {}).get("FIXTURE")} if self.fixture else {})}


def validate(df: pd.DataFrame, closures: pd.DataFrame, net: RoadNetwork, bucket_min: int = 10,
             horizons: int = 6, meta: dict | None = None) -> ForecastSnapshot:
    probs: list[str] = []
    miss = [c for c in REQUIRED if c not in df.columns]
    if miss:
        raise ForecastInvalid([f"missing columns {miss}"])
    if df.empty:
        raise ForecastInvalid(["empty forecast"])
    B = bucket_min * 60
    for c in ("model_version", "network_version", "issued_at"):
        if df[c].nunique() != 1:
            probs.append(f"{c} is not unique across rows ({df[c].nunique()} values)")
    if probs:
        raise ForecastInvalid(probs)
    t_issue = _utc(df.issued_at.iloc[0])
    if df.network_version.iloc[0] != net.version:
        probs.append(f"forecast network {df.network_version.iloc[0]} != routing network {net.version}")
    want_h = [bucket_min * (k + 1) for k in range(horizons)]
    if sorted(df.horizon_min.unique().tolist()) != want_h:
        probs.append(f"horizons {sorted(df.horizon_min.unique().tolist())} != {want_h}")
    if df.duplicated(["road_segment_id", "horizon_min"]).any():
        probs.append(f"{int(df.duplicated(['road_segment_id', 'horizon_min']).sum())} duplicate road/horizon keys")
    vf = pd.to_datetime(df.valid_from, utc=True)
    vt = pd.to_datetime(df.valid_to, utc=True)
    exp_from = t_issue + pd.to_timedelta((df.horizon_min.to_numpy() // bucket_min - 1) * B, unit="s")
    if (vf != exp_from).any() or ((vt - vf) != pd.Timedelta(seconds=B)).any():
        probs.append("valid_from/valid_to are not the contiguous [issued_at + 10(k-1), issued_at + 10k) intervals")
    bad_av = set(df.availability.unique()) - AVAILABILITY
    if bad_av:
        probs.append(f"unknown availability values {sorted(bad_av)}")
    bad_src = set(df.prediction_source.unique()) - SOURCES
    if bad_src:
        probs.append(f"unknown prediction_source values {sorted(bad_src)}")
    unknown = ~df.road_segment_id.isin(net.pos.keys())
    if unknown.any():
        probs.append(f"{int(unknown.sum())} rows for roads not in network {net.version}")
    usable = (df.availability == "open") | ((df.availability == "restricted") & (df.restriction_reason == PARTIAL))
    usable &= df.prediction_source != "none"
    tt = df.predicted_travel_time_sec.to_numpy(float)
    badtt = usable.to_numpy() & ~(np.isfinite(tt) & (tt > 0))
    if badtt.any():
        probs.append(f"{int(badtt.sum())} usable rows without a positive finite travel time")
    rep = df.prediction_source == "representative_road"
    if rep.any() and (~df.represented_by[rep].isin(net.pos.keys())).any():
        probs.append("representative_road rows point to roads outside the network")
    if closures is not None and len(closures):
        cmiss = [c for c in ("road_segment_id", "restriction", "closure_begin", "closure_end") if c not in closures]
        if cmiss:
            probs.append(f"closures missing columns {cmiss}")
        else:
            cb, ce = pd.to_datetime(closures.closure_begin, utc=True), pd.to_datetime(closures.closure_end, utc=True)
            if (ce <= cb).any():
                probs.append(f"{int((ce <= cb).sum())} closure intervals with end <= begin")
    if probs:
        raise ForecastInvalid(probs)

    R, H = net.n, horizons
    ri = df.road_segment_id.map(net.pos).to_numpy()
    ki = (df.horizon_min.to_numpy() // bucket_min - 1).astype(int)
    TT = np.full((R, H), np.nan)
    CG = np.full((R, H), np.nan)
    OK = np.zeros((R, H), bool)
    SRC = np.full((R, H), "none", object)
    TT[ri, ki] = np.where(usable, tt, np.nan)
    CG[ri, ki] = df.predicted_congestion_ratio.to_numpy(float)
    OK[ri, ki] = usable.to_numpy()
    SRC[ri, ki] = df.prediction_source.to_numpy()
    cl: dict[int, list] = {}
    unmatched_closures = 0
    if closures is not None and len(closures):
        for r in closures.itertuples():
            i = net.pos.get(r.road_segment_id)
            if i is None:
                unmatched_closures += 1
                continue
            cl.setdefault(i, []).append((_utc(r.closure_begin).timestamp(), _utc(r.closure_end).timestamp(),
                                         str(r.restriction)))
    h = hashlib.sha256()
    for a in (TT, OK):
        h.update(np.ascontiguousarray(np.nan_to_num(a, nan=-1.0)).tobytes())
    h.update(json.dumps(sorted((k, v) for k, vs in cl.items() for v in vs), default=str).encode())
    h.update(f"{t_issue.isoformat()}|{df.model_version.iloc[0]}".encode())
    prov = {c: (df[c].iloc[0].item() if hasattr(df[c].iloc[0], "item") else df[c].iloc[0])
            for c in PROVENANCE if c in df.columns}
    covered = np.isin(np.arange(R), ri)
    coverage = {"roads_in_network": R, "roads_with_rows": int(covered.sum()),
                "roads_usable_any_interval": int(OK.any(1).sum()),
                "roads_usable_all_intervals": int(OK.all(1).sum()),
                "availability_counts": df.availability.value_counts().to_dict(),
                "prediction_source_counts": df.prediction_source.value_counts().to_dict(),
                "closure_intervals": int(sum(len(v) for v in cl.values())),
                "closures_on_unknown_roads": unmatched_closures}
    return ForecastSnapshot(version=h.hexdigest()[:16], issued_at=t_issue.timestamp(), bucket_s=float(B), H=H,
                            tt=TT, cong=CG, ok=OK, source=SRC,
                            closures={k: tuple(v) for k, v in cl.items()},
                            model_version=str(df.model_version.iloc[0]), network_version=str(df.network_version.iloc[0]),
                            provenance={**prov, "meta": meta or {}}, coverage=coverage,
                            fixture=bool((df.prediction_source == "fixture").any()))


def load_files(path, net: RoadNetwork, bucket_min: int = 10, horizons: int = 6) -> ForecastSnapshot:
    p = Path(path)
    if not p.exists():
        raise ForecastInvalid([f"forecast file {p} not found"])
    cp = p.with_suffix(".closures.parquet")
    mp = p.with_suffix(".meta.json")
    df = pd.read_parquet(p)
    closures = pd.read_parquet(cp) if cp.exists() else None
    meta = json.loads(mp.read_text()) if mp.exists() else {}
    snap = validate(df, closures, net, bucket_min, horizons, meta)
    snap.provenance["source_file"] = str(p)
    return snap


class ForecastStore:
    """Holds the current validated snapshot. publish() swaps it atomically; a malformed replacement is refused and
    the previous one keeps serving."""

    def __init__(self, net: RoadNetwork, bucket_min: int = 10, horizons: int = 6, max_age_min: float = 20.0):
        self.net = net
        self.bucket_min, self.horizons, self.max_age_min = bucket_min, horizons, max_age_min
        self._snap: ForecastSnapshot | None = None
        self._lock = threading.Lock()
        self.last_error: str | None = None

    @property
    def current(self) -> ForecastSnapshot | None:
        return self._snap

    def publish(self, snap_or_path) -> ForecastSnapshot:
        try:
            snap = (snap_or_path if isinstance(snap_or_path, ForecastSnapshot)
                    else load_files(snap_or_path, self.net, self.bucket_min, self.horizons))
            if snap.network_version != self.net.version:
                raise ForecastInvalid([f"snapshot network {snap.network_version} != {self.net.version}"])
        except ForecastInvalid as e:
            self.last_error = str(e)
            raise
        with self._lock:
            if self._snap is not None and snap.issued_at < self._snap.issued_at:
                self.last_error = "refused: older than the current snapshot"
                raise ForecastInvalid([self.last_error])
            self._snap = snap
            self.last_error = None
        return snap

    def status(self, now: float) -> tuple[str, ForecastSnapshot | None]:
        s = self._snap
        if s is None:
            return "missing", None
        if s.age_min(now) > self.max_age_min:
            return "stale", s
        if now < s.issued_at:
            return "not_yet_valid", s
        return "ok", s
