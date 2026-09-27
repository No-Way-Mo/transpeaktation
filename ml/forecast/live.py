"""Live congestion map: Tiger + Mongo inputs -> forecaster -> Tiger prediction_metrics (+ Mongo forecast_runs).

Called on demand (the coordinator asks when a customer request finds its map older than one bucket), at most once per
10-min issue time: a map that already exists is reused, never recomputed.

Issue time = end of the newest COMPLETE 10-min bucket in Tiger traffic_metrics (a bucket counts once its TomTom rows
reach `min_complete_share` of the recent median; ingest lags real time by ~10-25 min), never later than now.

Inputs, all known at issue time:
  history   traffic_metrics of the `history_steps` completed buckets before issue, one congestion ratio per road x
            bucket by source priority tomtom > mapbox_route > mapbox_tiles. Muni is left out (AGENTS.md: it runs low
            and is never averaged with other sources). A road/bucket with no row is UNOBSERVED (the model has a
            missing flag; a missing mapbox_tiles row can mean free flow or no coverage, so it is never read as free
            flow). speed_mph = the model's own free-flow speed x (1 - ratio): the model was trained on congestion
            relative to its free flow, so the observed RATIO is transferred, not the provider's absolute speed.
  closures  Mongo road_incidents with is_closure and road ids overlapping [issue - history, issue + horizon):
            street_closures -> full; caltrans lane closures -> full when all lanes / type Full, else lane (lane
            closures neither block routing nor enter the model footprint). A DataSF special-event closure within
            500 m of an overlapping PredictHQ event becomes that event's `public_event` case (its hours; attendance
            left missing: PredictHQ's figure is a prediction, not the declared figure the model was trained with).
            PredictHQ events without a closure footprint cannot change this model's output and are not sent.

Output = the predict.py contract rows (one per canonical road x horizon), written to prediction_metrics in one
transaction (replacing any partial earlier write for the same model + issue time), THEN a forecast_runs document
{status: "ready", closures, coverage, identities}. A map without its ready document does not exist for readers.
The model was trained only on synthetic SUMO traffic; nothing here validates it on real traffic.
"""
from __future__ import annotations

import io
import math
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from .predict import Predictor, closure_cover

B = 600
SOURCES = ("tomtom", "mapbox_route", "mapbox_tiles")          # priority order
INPUT_SOURCE = "live_tiger_mongo"
MAP_COLUMNS = ["time", "model_version", "road_segment_id", "prediction_horizon_min", "current_speed_mph",
               "predicted_speed_mph", "predicted_delay_sec", "issued_at", "valid_to", "predicted_travel_time_sec",
               "predicted_congestion_ratio", "availability", "restriction_reason", "prediction_source",
               "represented_by", "network_version", "input_source"]


def _utc(t) -> pd.Timestamp:
    t = pd.Timestamp(t)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def _epoch(t) -> float:
    return _utc(t).timestamp()


# ---- pure transformations (unit-tested) --------------------------------------------------------------------------------
def choose_issue(bucket_counts: pd.DataFrame, now: float, min_complete_share: float = 0.5) -> float | None:
    """bucket_counts: time (bucket start), n (TomTom rows). Issue = end of the newest complete bucket, <= floor(now)."""
    if bucket_counts is None or bucket_counts.empty:
        return None
    bc = bucket_counts.assign(t=bucket_counts.time.map(_epoch)).sort_values("t")
    bc = bc[bc.t + B <= now]                                   # a bucket still in progress is never complete
    for i in range(len(bc) - 1, -1, -1):
        prev = bc.n.iloc[max(0, i - 6):i]
        if len(prev) == 0 or bc.n.iloc[i] >= min_complete_share * float(np.median(prev)):
            return float(bc.t.iloc[i] + B)
    return None


def fuse_history(traffic: pd.DataFrame, model_ids, ff_mph: np.ndarray, starts: np.ndarray) -> pd.DataFrame:
    """traffic rows (time, road_segment_id, source, congestion_ratio) -> predictor history rows for every model road x
    history bucket: time, road_segment_id, speed_mph, observed, closed (closed filled in by the caller)."""
    ids = pd.Index(list(map(str, model_ids)))
    T, N = len(starts), len(ids)
    ratio = np.full((T, N), np.nan)
    if len(traffic):
        t = traffic[traffic.source.isin(SOURCES) & traffic.congestion_ratio.notna()].copy()
        t["ti"] = np.searchsorted(starts, t.time.map(_epoch).to_numpy())
        t["ri"] = ids.get_indexer(t.road_segment_id.astype(str))
        t = t[(t.ri >= 0) & (t.ti < T) & (starts[np.minimum(t.ti, T - 1)] == t.time.map(_epoch).to_numpy())]
        t["prio"] = t.source.map({s: k for k, s in enumerate(SOURCES)})
        t = t.groupby(["ti", "ri", "prio"], as_index=False).congestion_ratio.mean()   # one value per source first
        t = t.sort_values("prio").drop_duplicates(["ti", "ri"], keep="first")        # then the best source
        ratio[t.ti.to_numpy(), t.ri.to_numpy()] = np.clip(t.congestion_ratio.to_numpy(float), 0.0, 1.0)
    obs = np.isfinite(ratio)
    speed = np.where(obs, ff_mph[None] * (1.0 - np.nan_to_num(ratio)), np.nan)
    return pd.DataFrame({"time": np.repeat(pd.to_datetime(starts, unit="s", utc=True), N),
                         "road_segment_id": np.tile(ids.to_numpy(), T), "speed_mph": speed.ravel(),
                         "observed": obs.ravel(), "closed": np.zeros(T * N, bool)})


def restriction_of(doc: dict) -> str:
    d = doc.get("details") or {}
    if doc.get("source") == "caltrans_lane_closures":
        full = str(d.get("lanes_closed", "")).lower() == "all" or str(d.get("type_of_closure", "")).lower() == "full"
        return "full" if full else "lane"
    return "full"                                            # DataSF street closures close the street segment


def _dist_m(a, b) -> float:
    k = math.cos(math.radians(37.77))
    return math.hypot((a[0] - b[0]) * 111_320 * k, (a[1] - b[1]) * 110_540)


def _points(geom: dict | None) -> list:
    if not geom:
        return []
    c = geom.get("coordinates")
    return [c] if geom.get("type") == "Point" else list(c or [])


def build_cases(incidents: list[dict], events: list[dict], issue: float, lo: float, hi: float,
                match_m: float = 500.0) -> list[dict]:
    """road_incidents closure docs + PredictHQ events -> predictor context cases (restrictions clipped to nothing:
    exact begin/end kept; open-ended closures end at `hi`, the end of the forecast horizon)."""
    cases = []
    for d in incidents:
        segs = [str(s) for s in (d.get("road_segment_ids") or [])]
        if not segs or d.get("start_time") is None:
            continue
        b = _epoch(d["start_time"])
        e = _epoch(d["end_time"]) if d.get("end_time") is not None else hi
        if not (b < hi and e > lo and e > b):
            continue
        case = {"case_num": f"{d.get('source')}:{d.get('source_id')}", "kind": "permit", "public_start": None,
                "public_end": None, "declared_attendance": None, "declared_attendance_source": None,
                "restrictions": [{"segment_ids": segs, "restriction": restriction_of(d),
                                  "begin": pd.Timestamp(b, unit="s", tz="UTC").isoformat(),
                                  "end": pd.Timestamp(e, unit="s", tz="UTC").isoformat(),
                                  "review_reason": f"{d.get('source')} ({d.get('category')})"}]}
        if (d.get("details") or {}).get("is_special_event"):
            pts = _points(d.get("location"))
            best = None
            for ev in events:
                es, ee = ev.get("start_time"), ev.get("end_time")
                if es is None or ee is None or not (_epoch(es) < e and _epoch(ee) > b):
                    continue
                loc = _points(ev.get("location"))
                dist = min((_dist_m(p, loc[0]) for p in pts), default=math.inf) if loc else math.inf
                if dist <= match_m and (best is None or dist < best[0]):
                    best = (dist, ev)
            if best is not None:
                ev = best[1]
                case.update({"kind": "public_event", "public_start": _utc(ev["start_time"]).isoformat(),
                             "public_end": _utc(ev["end_time"]).isoformat(), "event_key": str(ev.get("title")),
                             "event_id": str(ev.get("venue_id") or ev.get("title"))})
        cases.append(case)
    return cases


MAX_EVENT_CASES = 24


def event_case_nums(cases: list[dict], lo: float, hi: float, margin_s: float = 3600.0,
                    max_cases: int = MAX_EVENT_CASES) -> list[str]:
    """Cases for the model's event context: public events and closures that begin or end within `margin_s` of the
    history + horizon window, at most `max_cases` (public events first, then the closest in time to the window).
    A closure active throughout (e.g. weeks of construction) is already in the observed traffic, the `closed` flags
    and the closure-cover input; as event context its time features would be clipped constants. Each case expands
    to every road within 3 km: training runs had ~10 cases, a Friday night in SF has ~150 candidates (~1M
    case-road pairs, > 3.5 GB in the model, 35 s). Every case still reaches the closure table (availability,
    routing legality)."""
    ranked = []
    for c in cases:
        edges = [_epoch(x) for r in c["restrictions"] for x in (r["begin"], r["end"])]
        edges += [_epoch(c[k]) for k in ("public_start", "public_end") if c.get(k)]
        gap = min((0.0 if lo <= t <= hi else min(abs(t - lo), abs(t - hi)) for t in edges), default=float("inf"))
        if c["kind"] == "public_event" or gap <= margin_s:
            ranked.append((c["kind"] != "public_event", gap, c["case_num"]))
    return [n for _, _, n in sorted(ranked)[:max_cases]]


def mark_closed(hist: pd.DataFrame, cases: list[dict], model_ids, starts: np.ndarray) -> pd.DataFrame:
    """History `closed` = a full closure covered the whole bucket (same rule as the training exports)."""
    from .predict import closure_table
    cl = closure_table({"cases": cases})
    if cl.empty:
        return hist
    cover = closure_cover(cl, pd.Index(list(map(str, model_ids))), starts.astype(float), B)   # [T, N]
    hist = hist.copy()
    hist["closed"] = (cover >= 1.0).ravel()
    return hist


def map_rows(df: pd.DataFrame, hist: pd.DataFrame, length_m: np.ndarray, ff_mph: np.ndarray,
             all_ids: np.ndarray) -> pd.DataFrame:
    """predict.py forecast rows -> prediction_metrics rows (current_speed = last fused history bucket)."""
    last = hist[hist.time == hist.time.max()].set_index("road_segment_id").speed_mph
    ff_tt = pd.Series(length_m / (ff_mph / 2.2369362920544), index=all_ids)
    out = pd.DataFrame({
        "time": df.valid_from, "model_version": df.model_version, "road_segment_id": df.road_segment_id,
        "prediction_horizon_min": df.horizon_min.astype(int), "current_speed_mph": df.road_segment_id.map(last),
        "predicted_speed_mph": df.predicted_speed_mph,
        "predicted_delay_sec": df.predicted_travel_time_sec - df.road_segment_id.map(ff_tt),
        "issued_at": df.issued_at, "valid_to": df.valid_to, "predicted_travel_time_sec": df.predicted_travel_time_sec,
        "predicted_congestion_ratio": df.predicted_congestion_ratio, "availability": df.availability,
        "restriction_reason": df.restriction_reason, "prediction_source": df.prediction_source,
        "represented_by": df.represented_by, "network_version": df.network_version, "input_source": INPUT_SOURCE})
    return out[MAP_COLUMNS]


# ---- databases --------------------------------------------------------------------------------------------------------
class Stores:
    """Tiger (psycopg2) + Mongo (pymongo). Connections are opened per call: calls happen at most every few minutes."""

    def __init__(self, tiger_url: str | None = None, mongo_uri: str | None = None, mongo_db: str = "transpeaktation"):
        self.tiger_url = tiger_url or os.environ.get("TIGER_DATABASE_URL")
        self.mongo_uri = mongo_uri or os.environ.get("MONGODB_URI")
        if not self.tiger_url or not self.mongo_uri:
            raise SystemExit("TIGER_DATABASE_URL and MONGODB_URI must be set for live forecasts")
        self.mongo_db = mongo_db
        self._mongo = None

    @contextmanager
    def _pg(self):
        """One transaction: committed on success, rolled back on error, connection always closed."""
        import psycopg2
        c = psycopg2.connect(self.tiger_url, connect_timeout=15)
        try:
            with c:
                yield c
        finally:
            c.close()

    def db(self):
        if self._mongo is None:
            import pymongo
            self._mongo = pymongo.MongoClient(self.mongo_uri, serverSelectionTimeoutMS=15000, tz_aware=True)
        return self._mongo[self.mongo_db]

    def bucket_counts(self, since: float) -> pd.DataFrame:
        with self._pg() as c, c.cursor() as cur:
            cur.execute("SELECT time, count(*) FROM traffic_metrics WHERE source = 'tomtom' AND time >= %s "
                        "GROUP BY time ORDER BY time", (datetime.fromtimestamp(since, timezone.utc),))
            return pd.DataFrame(cur.fetchall(), columns=["time", "n"])

    def traffic(self, lo: float, hi: float) -> pd.DataFrame:
        with self._pg() as c, c.cursor() as cur:
            cur.execute("SELECT time, road_segment_id, source, congestion_ratio FROM traffic_metrics "
                        "WHERE time >= %s AND time < %s AND source = ANY(%s)",
                        (datetime.fromtimestamp(lo, timezone.utc), datetime.fromtimestamp(hi, timezone.utc),
                         list(SOURCES)))
            return pd.DataFrame(cur.fetchall(), columns=["time", "road_segment_id", "source", "congestion_ratio"])

    def closures(self, lo: float, hi: float) -> list[dict]:
        lo_d, hi_d = datetime.fromtimestamp(lo, timezone.utc), datetime.fromtimestamp(hi, timezone.utc)
        q = {"is_closure": True, "road_segment_ids.0": {"$exists": True}, "start_time": {"$lt": hi_d},
             "$or": [{"end_time": {"$gt": lo_d}}, {"end_time": None}]}
        proj = {"_id": 0, "source": 1, "source_id": 1, "category": 1, "details": 1, "location": 1,
                "road_segment_ids": 1, "start_time": 1, "end_time": 1}
        return list(self.db().road_incidents.find(q, proj))

    def events(self, lo: float, hi: float) -> list[dict]:
        lo_d, hi_d = datetime.fromtimestamp(lo, timezone.utc), datetime.fromtimestamp(hi, timezone.utc)
        return list(self.db().events.find({"start_time": {"$lt": hi_d}, "end_time": {"$gt": lo_d}},
                                          {"_id": 0, "title": 1, "venue_id": 1, "location": 1, "start_time": 1,
                                           "end_time": 1, "attendance": 1}))

    def find_run(self, run_id: str) -> dict | None:
        return self.db().forecast_runs.find_one({"_id": run_id, "status": "ready"})

    def write_map(self, rows: pd.DataFrame, run: dict) -> float:
        """Rows in one transaction (a partial earlier write for this model + issue is replaced), then the ready doc."""
        t0 = time.perf_counter()
        buf = io.StringIO()
        rows.to_csv(buf, index=False, header=False, na_rep="\\N", date_format="%Y-%m-%d %H:%M:%S%z")
        buf.seek(0)
        issue = run["issued_at"]
        with self._pg() as c, c.cursor() as cur:
            cur.execute("DELETE FROM prediction_metrics WHERE model_version = %s AND issued_at = %s "
                        "AND time >= %s AND time < %s",
                        (run["model_version"], issue, issue, issue + timedelta(seconds=B * run["horizons"])))
            cur.copy_expert(f"COPY prediction_metrics ({', '.join(MAP_COLUMNS)}) FROM STDIN WITH (FORMAT csv, "
                            f"NULL '\\N')", buf)
        run.setdefault("seconds", {})["write"] = round(time.perf_counter() - t0, 2)   # rows first, then the ready doc
        self.db().forecast_runs.replace_one({"_id": run["_id"]}, run, upsert=True)
        return run["seconds"]["write"]


# ---- the on-demand job --------------------------------------------------------------------------------------------------
def run_id(model_version: str, issue: float) -> str:
    return f"{model_version}|{pd.Timestamp(issue, unit='s', tz='UTC').isoformat()}"


class LiveForecaster:
    """ensure() = the congestion map for the newest complete bucket, computing it only if it does not exist yet.
    One computation at a time; concurrent callers wait for it and then reuse it."""

    def __init__(self, predictor: Predictor, stores: Stores, checkpoint_sha256: str = "",
                 min_complete_share: float = 0.5):
        self.p, self.stores, self.sha, self.share = predictor, stores, checkpoint_sha256, min_complete_share
        self.lock = threading.Lock()
        g = predictor.g
        self.model_ids = np.array(list(map(str, g.model_ids)))
        self.ff = g.free_flow_mph.astype(float)
        cfg = predictor.cfg.data
        self.Th, self.H = cfg.history_steps, cfg.horizon_steps
        roads = g.roads
        self.all_ids = roads.road_segment_id.astype(str).to_numpy()
        self.all_len = roads.length_m.to_numpy(float)
        self.all_ff = roads.free_flow_speed_mph.to_numpy(float)

    def ensure(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        with self.lock:
            counts = self.stores.bucket_counts(now - 3 * 3600)
            issue = choose_issue(counts, now, self.share)
            if issue is None:
                raise RuntimeError("no complete traffic bucket in Tiger in the last 3 h (is ingest running?)")
            rid = run_id(self.p.model_version, issue)
            doc = self.stores.find_run(rid)
            if doc is not None:
                return {**summary(doc), "reused": True}
            doc = self._compute(issue, rid)
            return {**summary(doc), "reused": False}

    def _compute(self, issue: float, rid: str) -> dict:
        t0 = time.perf_counter()
        starts = issue - B * np.arange(self.Th, 0, -1).astype(float)
        lo, hi = float(starts[0]), issue + B * self.H
        traffic = self.stores.traffic(lo, issue)
        cases = build_cases(self.stores.closures(lo, hi), self.stores.events(lo, hi), issue, lo, hi)
        hist = fuse_history(traffic, self.model_ids, self.ff, starts)
        hist = mark_closed(hist, cases, self.model_ids, starts)
        if not hist.observed.any():
            raise RuntimeError(f"no usable traffic observations before {pd.Timestamp(issue, unit='s', tz='UTC')}")
        ctx = {"issued_at": pd.Timestamp(issue, unit="s", tz="UTC").isoformat(),
               "network_version": self.p.network_version, "cases": cases,
               "event_cases": event_case_nums(cases, lo, hi),
               "provenance": {"source": INPUT_SOURCE, "synthetic": False,
                              "tiger": "traffic_metrics (tomtom > mapbox_route > mapbox_tiles; muni excluded)",
                              "mongo": "road_incidents closures, events"}}
        t1 = time.perf_counter()
        df, closures = self.p.frame(hist, ctx)
        df["input_source"] = INPUT_SOURCE
        t2 = time.perf_counter()
        rows = map_rows(df, hist, self.all_len, self.all_ff, self.all_ids)
        obs = hist.observed.to_numpy().reshape(self.Th, -1)
        issue_dt = datetime.fromtimestamp(issue, timezone.utc)
        doc = {"_id": rid, "status": "ready", "issued_at": issue_dt, "model_version": self.p.model_version,
               "network_version": self.p.network_version, "checkpoint_sha256": self.sha,
               "dataset_id": self.p.ck["dataset_id"], "training_source": f"sumo_synthetic:{self.p.manifest['batch']}",
               "synthetic_training": True, "input_source": INPUT_SOURCE, "horizons": self.H, "bucket_min": B // 60,
               "rows": len(rows), "created_at": datetime.now(timezone.utc),
               "closures": [{"road_segment_id": r.road_segment_id, "case_num": r.case_num, "kind": r.kind,
                             "restriction": r.restriction, "closure_begin": r.closure_begin.to_pydatetime(),
                             "closure_end": r.closure_end.to_pydatetime()} for r in closures.itertuples()],
               "coverage": {"model_roads": int(obs.shape[1]),
                            "observed_share_by_bucket": [round(float(x), 4) for x in obs.mean(1)],
                            "observed_any_bucket": int(obs.any(0).sum()),
                            "traffic_rows_by_source": traffic.source.value_counts().to_dict(),
                            "cases": len(cases), "public_event_cases": sum(c["kind"] == "public_event" for c in cases),
                            "event_context_cases": len(ctx["event_cases"]),
                            "closure_rows": len(closures),
                            "availability_counts": df.availability.value_counts().to_dict()},
               "seconds": {"inputs": round(t1 - t0, 2), "model": round(t2 - t1, 2)},
               "note": "model trained on synthetic SUMO scenarios; not validated on real traffic; no uncertainty"}
        self.stores.write_map(rows, doc)
        return doc


def summary(doc: dict) -> dict:
    return {"run_id": doc["_id"], "issued_at": _utc(doc["issued_at"]).isoformat(),
            "model_version": doc["model_version"], "network_version": doc["network_version"],
            "rows": doc["rows"], "coverage": doc.get("coverage"), "seconds": doc.get("seconds"),
            "checkpoint_sha256": doc.get("checkpoint_sha256")}
