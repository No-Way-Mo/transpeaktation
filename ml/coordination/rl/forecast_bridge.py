"""Causal traffic history from the running simulation + a frozen forecaster refreshed from THAT history.

Measurement matches the batch export the forecaster was trained on (SUMO edgeData, 10-min buckets): per road,
sampled vehicle-seconds and travelled distance are summed over every simulation step of the bucket;
speed = distance / sampled seconds, observed = sampled > 0; unobserved roads stay missing (no filling, no noise).
Sampling is every `step_s` seconds from per-vehicle TraCI subscriptions (edgeData integrates each 1 s step; with
step_s = 1 the two agree up to SUMO's sub-step position interpolation). `closed` = a full restriction overlaps the
bucket (same rule as eventsim.simulate.closure_mask).

A bucket is used only after it has finished. Each policy run refreshes the forecast from its own history; nothing
is borrowed from another run.

Modes: `model` (trained checkpoint; the default), `fixture_debug` / `persistence_debug` (labeled development
stand-ins, refused outside debug runs).
"""
from __future__ import annotations

from collections import deque

import numpy as np
import pandas as pd

from ..fixture import build as fixture_build
from ..forecast_store import ForecastSnapshot, validate
from ..network import RoadNetwork

MPS_TO_MPH = 2.2369362920544
_PREDICTORS: dict = {}


def predictor(checkpoint: str, device: str = ""):
    """One loaded forecaster per process and checkpoint (never reloaded per refresh)."""
    key = (str(checkpoint), device)
    if key not in _PREDICTORS:
        from forecast.predict import Predictor
        _PREDICTORS[key] = Predictor(checkpoint, device or None)
    return _PREDICTORS[key]


class Measurements:
    def __init__(self, net: RoadNetwork, bucket_s: float = 600.0, keep: int = 12):
        self.net, self.bucket_s = net, bucket_s
        self.sampled = np.zeros(net.n)
        self.dist = np.zeros(net.n)
        self.history: deque = deque(maxlen=keep)     # (bucket_start_local_s, speed_mph[R], observed[R])

    def sample(self, roads: np.ndarray, speeds: np.ndarray, dt: float) -> None:
        if len(roads):
            np.add.at(self.sampled, roads, dt)
            np.add.at(self.dist, roads, speeds * dt)

    def close_bucket(self, start_local_s: float) -> None:
        obs = self.sampled > 0
        spd = np.where(obs, self.dist / np.maximum(self.sampled, 1e-9) * MPS_TO_MPH, np.nan)
        self.history.append((float(start_local_s), spd.astype(np.float32), obs))
        self.sampled[:] = 0
        self.dist[:] = 0

    def state(self) -> dict:
        return {"starts": np.array([h[0] for h in self.history]), "speed": np.array([h[1] for h in self.history]),
                "observed": np.array([h[2] for h in self.history]), "sampled": self.sampled, "dist": self.dist}

    def load_state(self, s: dict) -> None:
        self.history.clear()
        for t, sp, ob in zip(s["starts"], s["speed"], s["observed"]):
            self.history.append((float(t), sp, ob.astype(bool)))
        self.sampled[:] = s["sampled"]
        self.dist[:] = s["dist"]


def closed_flags(net: RoadNetwork, restrictions: list, start_s: float, bucket_s: float) -> np.ndarray:
    out = np.zeros(net.n, bool)
    for r in restrictions:
        if r["restriction"] != "full" or not (r["begin_s"] < start_s + bucket_s and r["end_s"] > start_s):
            continue
        for s in r["segment_ids"]:
            i = net.pos.get(s)
            if i is not None:
                out[i] = True
    return out


def closures_table(spec) -> pd.DataFrame:
    rows = [{"road_segment_id": s, "case_num": "scenario", "kind": "restriction", "restriction": r["restriction"],
             "closure_begin": pd.Timestamp(spec.utc(r["begin_s"]), unit="s", tz="UTC"),
             "closure_end": pd.Timestamp(spec.utc(r["end_s"]), unit="s", tz="UTC")}
            for r in spec.restrictions for s in r["segment_ids"]]
    return pd.DataFrame(rows, columns=["road_segment_id", "case_num", "kind", "restriction", "closure_begin",
                                       "closure_end"])


class ForecastBridge:
    def __init__(self, net: RoadNetwork, spec, mode: str, checkpoint: str = "", device: str = "",
                 history_steps: int = 6, bucket_s: float = 600.0, allow_debug: bool = False):
        if mode not in ("model", "fixture_debug", "persistence_debug"):
            raise ValueError(f"unknown forecast mode {mode!r}")
        if mode != "model" and not allow_debug:
            raise SystemExit(f"forecast mode {mode!r} is a labeled debug stand-in; pass --debug-forecast to use it")
        self.net, self.spec, self.mode = net, spec, mode
        self.history_steps, self.bucket_s = history_steps, bucket_s
        self.pred = predictor(checkpoint, device) if mode == "model" else None
        if self.pred is not None and self.pred.network_version != net.version:
            raise SystemExit(f"forecaster network {self.pred.network_version} != routing network {net.version}")
        self.closures = closures_table(spec)
        self.refreshes = 0

    def ready(self, m: Measurements) -> bool:
        return len(m.history) >= self.history_steps

    def refresh(self, m: Measurements, issue_local_s: float) -> ForecastSnapshot:
        """Forecast issued at the end of the last completed bucket, from this run's own measurements."""
        hist = list(m.history)[-self.history_steps:]
        if len(hist) < self.history_steps or abs(hist[-1][0] + self.bucket_s - issue_local_s) > 1e-6:
            raise ValueError("need the last completed buckets up to the issue time")
        issued = self.spec.utc(issue_local_s)
        self.refreshes += 1
        if self.mode == "model":
            rows = []
            for t, spd, obs in hist:
                rows.append(pd.DataFrame({
                    "time": pd.Timestamp(self.spec.utc(t), unit="s", tz="UTC"), "road_segment_id": self.net.ids,
                    "speed_mph": spd, "observed": obs,
                    "closed": closed_flags(self.net, self.spec.restrictions, t, self.bucket_s)}))
            ctx = {**self.spec.forecast_context, "issued_at": pd.Timestamp(issued, unit="s", tz="UTC").isoformat(),
                   "network_version": self.net.version,
                   "provenance": {"source": "sumo_synthetic_interactive", "synthetic": True,
                                  "scenario": self.spec.scenario_id}}
            df, cl = self.pred.frame(pd.concat(rows, ignore_index=True), ctx)
            cd = self.pred.cfg.data   # horizon / bucket come from the loaded checkpoint (6 for v2, 18 for v4_h18)
            if cd.bucket_min * 60 != self.bucket_s or cd.history_steps != self.history_steps:
                raise ValueError("forecaster bucket/history differ from the bridge's measurements")
            return validate(df, cl, self.net, cd.bucket_min, cd.horizon_steps,
                            meta={"mode": "model", "issued_local_s": issue_local_s})
        if self.mode == "fixture_debug":
            df, cl, meta = fixture_build(self.net, pd.Timestamp(issued, unit="s", tz="UTC"), self.closures)
            return validate(df, cl, self.net, meta={**meta, "mode": "fixture_debug"})
        return self._persistence(hist, issued)

    def _persistence(self, hist, issued: float) -> ForecastSnapshot:
        """DEBUG: last observed speed (<= 2 buckets old) for every horizon, else free flow. Labeled as fixture."""
        net = self.net
        spd = np.full(net.n, np.nan)
        for _, s, o in hist[-3:]:
            spd = np.where(o, s, spd)
        tt = np.where(np.isfinite(spd), net.length_m / np.maximum(spd / MPS_TO_MPH, 0.1), net.ff_tt_s)
        df, cl, meta = fixture_build(net, pd.Timestamp(issued, unit="s", tz="UTC"), self.closures)
        k = df.predicted_travel_time_sec.notna() & (df.prediction_source == "fixture")
        rid = df.road_segment_id.map(net.pos).to_numpy()
        df.loc[k, "predicted_travel_time_sec"] = tt[rid[k.to_numpy()]]
        df["model_version"] = "persistence_debug"
        return validate(df, cl, net, meta={"mode": "persistence_debug"})
