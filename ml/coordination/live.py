"""Live input mode: routing reads the congestion map the forecaster wrote to the databases, on demand.

    customer request -> coordinator: is my map older than one bucket (and not checked in the last `check_s`)?
        no  -> route on it
        yes -> ask the forecaster (POST /v1/live/forecast): it returns the newest complete bucket's run, computing it
               first if nobody has (forecast/live.py) -> if newer than mine, read it from Tiger prediction_metrics
               (+ exact closures from the Mongo forecast_runs doc), validate, publish, re-time live reservations.
        The request waits for this only when it has no usable map (none yet, or stale); otherwise it is routed on the
        current map while the refresh runs in the background.

Nothing runs without requests except the reservation expiry sweep. Clock = wall time (UTC). The forecast covers
[issue, issue + 60 min) and ingest lags real time by ~10-25 min, so trips ending past the covered interval are
refused as beyond the horizon rather than priced with made-up costs.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import timedelta

import pandas as pd

from .config import Config
from .coordinator import Coordinator
from .forecast_store import ForecastInvalid, ForecastStore, validate
from .network import RoadNetwork
from .replay import ForecastClient
from .schemas import iso
from .storage import Storage

B = 600


class MapReader:
    """Reads one ready run (Mongo forecast_runs doc + Tiger prediction_metrics rows) in the forecast contract shape."""

    def __init__(self, tiger_url: str | None = None, mongo_uri: str | None = None, mongo_db: str = "transpeaktation"):
        self.tiger_url = tiger_url or os.environ.get("TIGER_DATABASE_URL")
        self.mongo_uri = mongo_uri or os.environ.get("MONGODB_URI")
        if not self.tiger_url or not self.mongo_uri:
            raise SystemExit("TIGER_DATABASE_URL and MONGODB_URI must be set for --input live")
        self.mongo_db, self._mongo = mongo_db, None

    def run(self, run_id: str) -> dict:
        if self._mongo is None:
            import pymongo
            self._mongo = pymongo.MongoClient(self.mongo_uri, serverSelectionTimeoutMS=15000, tz_aware=True)
        doc = self._mongo[self.mongo_db].forecast_runs.find_one({"_id": run_id, "status": "ready"})
        if doc is None:
            raise ForecastInvalid([f"forecast run {run_id} not found or not ready"])
        return doc

    def read(self, run: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
        import psycopg2
        issue = run["issued_at"]
        c = psycopg2.connect(self.tiger_url, connect_timeout=15)
        try:
            with c, c.cursor() as cur:
                cur.execute("SELECT road_segment_id, issued_at, time, valid_to, prediction_horizon_min, "
                            "predicted_travel_time_sec, predicted_speed_mph, predicted_congestion_ratio, availability, "
                            "restriction_reason, prediction_source, represented_by, model_version, network_version, "
                            "input_source FROM prediction_metrics WHERE model_version = %s AND issued_at = %s "
                            "AND time >= %s AND time < %s",
                            (run["model_version"], issue, issue, issue + timedelta(seconds=B * run["horizons"])))
                rows = cur.fetchall()
        finally:
            c.close()
        return to_contract(rows, run)


COLUMNS = ["road_segment_id", "issued_at", "valid_from", "valid_to", "horizon_min", "predicted_travel_time_sec",
           "predicted_speed_mph", "predicted_congestion_ratio", "availability", "restriction_reason",
           "prediction_source", "represented_by", "model_version", "network_version", "input_source"]


def to_contract(rows, run: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = pd.DataFrame(rows, columns=COLUMNS)
    for k in ("issued_at", "valid_from", "valid_to"):
        df[k] = pd.to_datetime(df[k], utc=True)
    for k in ("predicted_travel_time_sec", "predicted_speed_mph", "predicted_congestion_ratio"):
        df[k] = pd.to_numeric(df[k], errors="coerce")
    for k in ("dataset_id", "training_source", "synthetic_training"):
        df[k] = run.get(k)
    cl = pd.DataFrame(run.get("closures") or [], columns=["road_segment_id", "case_num", "kind", "restriction",
                                                          "closure_begin", "closure_end"])
    for k in ("closure_begin", "closure_end"):
        cl[k] = pd.to_datetime(cl[k], utc=True)
    return df, cl


class LiveRuntime:
    """Owns the live coordinator; `before_request()` keeps its map current, driven by customer requests only."""

    def __init__(self, cfg: Config, net: RoadNetwork, client, reader, selector: str | None = None, clock=time.time):
        self.cfg, self.net, self.client, self.reader, self.clock = cfg, net, client, reader, clock
        lc = cfg.live
        state = cfg.path(lc.state_dir)
        state.mkdir(parents=True, exist_ok=True)
        fc = cfg.forecast
        store = ForecastStore(net, fc.bucket_min, fc.horizons, fc.max_issue_age_min)
        self.coord = Coordinator(cfg, net, store, Storage(state / "ledger_live.sqlite"), clock=clock, selector=selector)
        self._lock = threading.Lock()
        self.last_check: float = 0.0
        self.last_refresh: dict | None = None
        self.last_error: str | None = None
        self.failures = 0

    def _due(self, now: float) -> bool:
        snap = self.coord.store.current
        if snap is None:
            return now - self.last_check >= self.cfg.live.retry_s or self.last_check == 0.0
        return now - snap.issued_at >= B and now - self.last_check >= self.cfg.live.check_s

    def before_request(self) -> None:
        now = self.clock()
        if not self._due(now):
            return
        status, _ = self.coord.store.status(now)
        if status == "ok":                                        # usable map: refresh without making anyone wait
            if self._lock.acquire(blocking=False):
                threading.Thread(target=self._refresh_locked, daemon=True, name="live-refresh").start()
            return
        if self._lock.acquire(timeout=self.cfg.live.wait_s):     # no usable map: this request waits for one
            self._refresh_locked()

    def _refresh_locked(self) -> None:
        try:
            self.refresh()
        finally:
            self._lock.release()

    def refresh(self) -> dict | None:
        """Ask the forecaster for the newest map; load it if newer than the current one."""
        now = self.clock()
        if not self._due(now):                                    # another request refreshed while we waited
            return None
        self.last_check = now
        t0 = time.perf_counter()
        try:
            r = self.client.live()
            cur = self.coord.store.current
            issue = pd.Timestamp(r["issued_at"]).timestamp()
            if cur is not None and issue <= cur.issued_at:
                self.failures, self.last_error = 0, None
                return None
            run = self.reader.run(r["run_id"])
            df, cl = self.reader.read(run)
            fc = self.cfg.forecast
            snap = validate(df, cl, self.net, fc.bucket_min, fc.horizons,
                            {"input_mode": "live", "run_id": r["run_id"], "coverage": run.get("coverage")})
            res = self.coord.refresh_forecast(snap)
            if not res.get("published"):
                raise ForecastInvalid([res.get("error", "refused")])
            self.last_refresh = {"run_id": r["run_id"], "issued_at": iso(snap.issued_at),
                                 "forecast_version": snap.version, "reused_by_forecaster": r.get("reused"),
                                 "forecaster_seconds": r.get("seconds"), "retimed": res["retimed"],
                                 "latency_s": round(time.perf_counter() - t0, 2), "at": iso(now),
                                 "observed_share_last_bucket": ((run.get("coverage") or {})
                                                                .get("observed_share_by_bucket") or [None])[-1]}
            self.failures, self.last_error = 0, None
            return self.last_refresh
        except Exception as e:                                    # keep the last good map until it goes stale
            self.failures += 1
            self.last_error = f"{type(e).__name__}: {e}"[:500]
            print(f"live refresh failed ({self.failures}): {self.last_error}", flush=True)
            return None

    def info(self) -> dict:
        return {"input_mode": "live",
                "note": "congestion map from Tiger traffic_metrics + Mongo closures/events via a forecaster trained "
                        "on synthetic SUMO traffic (not validated on real traffic)",
                "last_refresh": self.last_refresh, "last_check": iso(self.last_check) if self.last_check else None,
                "refresh_failures": self.failures, "last_refresh_error": self.last_error}


def from_config(cfg: Config, net: RoadNetwork, selector: str | None = None) -> LiveRuntime:
    client = ForecastClient(cfg.live.forecast_url, os.environ.get("FORECAST_API_TOKEN"), cfg.live.timeout_s)
    return LiveRuntime(cfg, net, client, MapReader(), selector)
