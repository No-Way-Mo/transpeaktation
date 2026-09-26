"""Reads what ingest/ writes (and ml/ will write), plus trip requests. Optional: every call returns None when
its database isn't configured or reachable, and the planner falls back (demo events, no closures/traffic).

Mongo (MONGODB_URI):  events, venues, road_incidents (read) · trips (write)
Tiger (TIGER_DATABASE_URL): traffic_metrics, prediction_metrics (read)
Field names follow AGENTS.md "Data stores" and ingest/DESIGN.md.
"""
from __future__ import annotations

import math
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from .model import LIVE_WINDOW, OPEN_ENDED, SF_TZ

_INGEST_ENV = Path(__file__).resolve().parent.parent.parent / "ingest" / ".env"
PLACEHOLDERS = ("<password>", "<db_password>")
BACKOFF_S = 60          # after a failure, skip that database for a minute instead of stalling every request
TRAFFIC_MAX_AGE = timedelta(minutes=40)
TRAFFIC_SOURCES = ("tomtom", "mapbox_route", "mapbox_tiles")  # best first; muni runs low (bus stops), not used
BUCKET = timedelta(minutes=10)       # ingest's traffic_metrics time step (AGENTS.md)
TYPICAL_WEEKS = 4


def typical_buckets(t: datetime, now: datetime) -> list[datetime]:
    """t's 10-min bucket start on the same SF weekday and wall-clock time in the TYPICAL_WEEKS most recent weeks
    before now (for a trip weeks ahead, the weeks before it haven't happened yet). Stepped in SF local time so a
    DST change in between doesn't shift the hour."""
    local, out, k = t.astimezone(SF_TZ), [], 1
    while len(out) < TYPICAL_WEEKS:
        u = (local - timedelta(weeks=k)).astimezone(timezone.utc)
        u -= timedelta(minutes=u.minute % 10, seconds=u.second, microseconds=u.microsecond)
        if u <= now:
            out.append(u)
        k += 1
    return out


def _url(name: str) -> str | None:
    """Env var, skipping the .env.example placeholders; locally falls back to ingest/.env like MAPBOX_TOKEN does."""
    for v in (os.environ.get(name), dotenv_values(_INGEST_ENV).get(name) if _INGEST_ENV.exists() else None):
        v = (v or "").strip().strip('"')
        if v and not any(p in v for p in PLACEHOLDERS):
            return v
    return None


class _Breaker:
    def __init__(self) -> None:
        self.off_until = 0.0
        self.error: str | None = None

    def ok(self) -> bool:
        return time.monotonic() >= self.off_until

    def trip(self, e: Exception) -> None:
        self.off_until = time.monotonic() + BACKOFF_S
        self.error = f"{type(e).__name__}: {str(e)[:120]}"


class Store:
    def __init__(self) -> None:
        self._mongo = None
        self._pg = None
        self._pg_lock = threading.Lock()
        self.mongo_breaker, self.tiger_breaker = _Breaker(), _Breaker()

    # --- connections -----------------------------------------------------------------------------------------
    def db(self):
        if self._mongo is None:
            url = _url("MONGODB_URI")
            if not url:
                return None
            from pymongo import MongoClient
            self._mongo = MongoClient(url, serverSelectionTimeoutMS=3000, connectTimeoutMS=3000, tz_aware=True,
                                      appname="transpeaktation-api")
        return self._mongo.get_default_database(default="transpeaktation")

    def _tiger(self):
        if self._pg is None or self._pg.closed:
            url = _url("TIGER_DATABASE_URL")
            if not url:
                return None
            import psycopg
            self._pg = psycopg.connect(url, connect_timeout=3, autocommit=True, application_name="transpeaktation-api")
        return self._pg

    def _mongo_call(self, fn):
        if not self.mongo_breaker.ok():
            return None
        try:
            db = self.db()
            return None if db is None else fn(db)
        except Exception as e:  # unreachable / auth / timeout: degrade, don't fail the request
            self.mongo_breaker.trip(e)
            return None

    def _tiger_call(self, sql: str, params: tuple) -> list[tuple] | None:
        if not self.tiger_breaker.ok():
            return None
        with self._pg_lock:
            try:
                conn = self._tiger()
                if conn is None:
                    return None
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    return cur.fetchall()
            except Exception as e:
                self.tiger_breaker.trip(e)
                if self._pg is not None:
                    self._pg.close()
                return None

    def status(self) -> dict[str, str]:
        def one(name: str, breaker: _Breaker) -> str:
            if not _url(name):
                return "not configured"
            return "ready" if breaker.ok() else f"backing off: {breaker.error}"
        return {"mongo": one("MONGODB_URI", self.mongo_breaker), "tiger": one("TIGER_DATABASE_URL", self.tiger_breaker)}

    # --- reads -----------------------------------------------------------------------------------------------
    def events_between(self, t0: datetime, t1: datetime) -> list[dict] | None:
        """Active events overlapping [t0, t1], each with its venue doc (capacity, keys, drop_off) under `venue`.
        None = no database; [] with `events_empty` = the collection has nothing yet (planner uses demo events)."""
        def q(db):
            if db.events.estimated_document_count() == 0:
                return None
            found = list(db.events.find(
                {"status": "active", "start_time": {"$lte": t1},
                 "$or": [{"end_time": {"$gte": t0}}, {"end_time": None, "start_time": {"$gte": t0 - timedelta(hours=4)}}]},
                {"title": 1, "category": 1, "start_time": 1, "end_time": 1, "location": 1, "venue_id": 1,
                 "capacity": 1, "attendance": 1, "rank": 1}).limit(300))
            venues = {v["_id"]: v for v in db.venues.find({"_id": {"$in": [e.get("venue_id") for e in found if e.get("venue_id")]}})}
            for e in found:
                e["venue"] = venues.get(e.get("venue_id"))
            return found
        return self._mongo_call(q)

    def incidents_on(self, segment_ids: list[str], t0: datetime, t1: datetime) -> list[dict] | None:
        """road_incidents touching these segments whose time span overlaps [t0, t1]. One with no end time counts
        for OPEN_ENDED after it started, so today's crash doesn't block a trip next week."""
        if not segment_ids:
            return []
        return self._mongo_call(lambda db: list(db.road_incidents.find(
            {"road_segment_ids": {"$in": segment_ids},
             "$and": [{"$or": [{"start_time": {"$lte": t1}}, {"start_time": None}]},
                      # no published end (crashes, dispatch calls): active OPEN_ENDED from its start, never indefinitely
                      {"$or": [{"end_time": {"$gte": t0}}, {"end_time": None, "start_time": {"$gte": t0 - OPEN_ENDED}}]}]},
            {"source": 1, "source_id": 1, "incident_type": 1, "category": 1, "is_closure": 1, "start_time": 1,
             "end_time": 1, "road_segment_ids": 1, "details.name": 1, "details.street": 1,
             "details.location_text": 1, "details.call_type": 1, "details.route": 1}).limit(500)))

    def traffic_latest(self, segment_ids: list[str]) -> list[dict] | None:
        """Newest observation per segment and source within TRAFFIC_MAX_AGE (Tiger traffic_metrics)."""
        if not segment_ids:
            return []
        rows = self._tiger_call(
            "SELECT DISTINCT ON (road_segment_id, source) road_segment_id, source, time, speed_mph, "
            "free_flow_speed_mph, congestion_ratio FROM traffic_metrics "
            "WHERE road_segment_id = ANY(%s) AND source = ANY(%s) AND time > now() - %s "
            "ORDER BY road_segment_id, source, time DESC",
            (segment_ids, list(TRAFFIC_SOURCES), TRAFFIC_MAX_AGE))
        cols = ("road_segment_id", "source", "time", "speed_mph", "free_flow_speed_mph", "congestion_ratio")
        return None if rows is None else [dict(zip(cols, r)) for r in rows]

    def traffic_at(self, segment_ids: list[str], t: datetime, now: datetime) -> tuple[list[dict] | None, str]:
        """Traffic for a trip at `t`, and what kind it is:
        live      t within LIVE_WINDOW of now: the newest readings (traffic_latest)
        observed  t in the past: the newest readings at or before t (TRAFFIC_MAX_AGE), i.e. what we saw then
        typical   t in the future: the same SF weekday + 10-min bucket averaged over the TYPICAL_WEEKS most
                  recent weeks; stand-in until ml/ writes prediction_metrics
        """
        if abs(t - now) <= LIVE_WINDOW:
            return self.traffic_latest(segment_ids), "live"
        if not segment_ids:
            return [], "observed" if t < now else "typical"
        cols = ("road_segment_id", "source", "time", "speed_mph", "free_flow_speed_mph", "congestion_ratio")
        if t < now:
            rows = self._tiger_call(
                "SELECT DISTINCT ON (road_segment_id, source) road_segment_id, source, time, speed_mph, "
                "free_flow_speed_mph, congestion_ratio FROM traffic_metrics "
                "WHERE road_segment_id = ANY(%s) AND source = ANY(%s) AND time > %s AND time <= %s "
                "ORDER BY road_segment_id, source, time DESC",
                (segment_ids, list(TRAFFIC_SOURCES), t - TRAFFIC_MAX_AGE, t))
            return (None if rows is None else [dict(zip(cols, r)) for r in rows]), "observed"
        rows = self._tiger_call(
            "SELECT road_segment_id, source, max(time), avg(speed_mph), avg(free_flow_speed_mph), "
            "avg(congestion_ratio) FROM traffic_metrics "
            "WHERE road_segment_id = ANY(%s) AND source = ANY(%s) AND time = ANY(%s) "
            "GROUP BY road_segment_id, source",
            (segment_ids, list(TRAFFIC_SOURCES), typical_buckets(t, now)))
        return (None if rows is None else [dict(zip(cols, r)) for r in rows]), "typical"

    def predictions(self, segment_ids: list[str], t0: datetime, t1: datetime) -> list[dict] | None:
        """ml/'s forecasts (Tiger prediction_metrics; `time` = the moment predicted for) around the trip."""
        if not segment_ids:
            return []
        rows = self._tiger_call(
            "SELECT road_segment_id, time, predicted_delay_sec, model_version FROM prediction_metrics "
            "WHERE road_segment_id = ANY(%s) AND time BETWEEN %s AND %s",
            (segment_ids, t0 - timedelta(minutes=15), t1 + timedelta(minutes=15)))
        cols = ("road_segment_id", "time", "predicted_delay_sec", "model_version")
        return None if rows is None else [dict(zip(cols, r)) for r in rows]

    def trips_to(self, lon: float, lat: float, t0: datetime, t1: datetime, radius_m: float = 400) -> int | None:
        """Other riders heading to about the same place: logged trips (Mongo trips) ending within ~radius_m
        (a box; trips store ~100 m rounded points) that depart in [t0, t1]."""
        dlat, dlon = radius_m / 111_132, radius_m / (111_320 * math.cos(math.radians(lat)))
        return self._mongo_call(lambda db: db.trips.count_documents({
            "destination.lat": {"$gte": lat - dlat, "$lte": lat + dlat},
            "destination.lon": {"$gte": lon - dlon, "$lte": lon + dlon},
            "depart_at": {"$gte": t0, "$lte": t1}}))

    # --- writes ----------------------------------------------------------------------------------------------
    def save_trip(self, doc: dict[str, Any]) -> bool:
        """One trip request (Mongo trips): the start of real demand data for ml/. No user identity is stored."""
        return self._mongo_call(lambda db: db.trips.insert_one(doc).acknowledged) or False
