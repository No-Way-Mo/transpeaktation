"""Reads what ingest/ writes (and ml/ will write), plus trip requests.

Store (the trip planner, /plan): optional, every call returns None when its database isn't configured or
reachable, and the planner falls back (demo events, no closures/traffic).
  Mongo (MONGODB_URI):  events, venues, road_incidents (read) · trips (write)
  Tiger (TIGER_DATABASE_URL): traffic_metrics, prediction_metrics (read)

Map views (/events with a window, /road-conditions, /traffic): find_* below. Shapes follow
contracts/map_context.schema.json and only those fields leave the API: no raw source rows, no provenance, no
credentials. A missing database raises StoreUnavailable (the API answers 503; routing is unaffected). Blocking
(pymongo / psycopg); main.py calls them in a thread.

Field names follow AGENTS.md "Data stores" and ingest/DESIGN.md.
"""
from __future__ import annotations

import math
import os
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from dotenv import dotenv_values

from .model import LIVE_WINDOW, NOT_A_DELAY, OPEN_ENDED, SF_TZ

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

    def closure_events(self, t0: datetime, t1: datetime) -> list[dict] | None:
        """DataSF special-event closures as events (find_closure_events): the same ones /events puts on the map, so
        the plan and ml/ see them too until ingest merges them into `events`."""
        return self._mongo_call(lambda db: find_closure_events(db, t0, t1))

    def incidents_on(self, segment_ids: list[str], t0: datetime, t1: datetime) -> list[dict] | None:
        """road_incidents touching these segments whose time span overlaps [t0, t1]. One with no end time counts
        for OPEN_ENDED after it started, so today's crash doesn't block a trip next week. Closures and incidents
        first, then permits (NOT_A_DELAY: ~11k active at a time), each up to 500, so permits can't crowd them out."""
        if not segment_ids:
            return []
        return self._mongo_call(lambda db: [d for cat in ({"$nin": sorted(NOT_A_DELAY)}, {"$in": sorted(NOT_A_DELAY)})
                                            for d in db.road_incidents.find(
            {"road_segment_ids": {"$in": segment_ids}, "category": cat,
             "$and": [{"$or": [{"start_time": {"$lte": t1}}, {"start_time": None}]},
                      # no published end (crashes, dispatch calls): active OPEN_ENDED from its start, never indefinitely
                      {"$or": [{"end_time": {"$gte": t0}}, {"end_time": None, "start_time": {"$gte": t0 - OPEN_ENDED}}]}]},
            {"source": 1, "source_id": 1, "incident_type": 1, "category": 1, "is_closure": 1, "start_time": 1,
             "end_time": 1, "road_segment_ids": 1, "details.name": 1, "details.street": 1,
             "details.location_text": 1, "details.call_type": 1, "details.route": 1}).limit(500)])

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
        (a box; trips store ~100 m rounded points) that depart in [t0, t1] and haven't arrived yet."""
        dlat, dlon = radius_m / 111_132, radius_m / (111_320 * math.cos(math.radians(lat)))
        return self._mongo_call(lambda db: db.trips.count_documents({
            "destination.lat": {"$gte": lat - dlat, "$lte": lat + dlat},
            "destination.lon": {"$gte": lon - dlon, "$lte": lon + dlon},
            "depart_at": {"$gte": t0, "$lte": t1}, "arrived_at": None}))  # None also matches older trips without it

    # --- writes ----------------------------------------------------------------------------------------------
    def save_trip(self, doc: dict[str, Any]) -> bool:
        """One trip request (Mongo trips): the start of real demand data for ml/. No user identity is stored."""
        return self._mongo_call(lambda db: db.trips.insert_one(doc).acknowledged) or False

    def mark_arrived(self, trip_id: str, at: datetime) -> int | None:
        """Set a trip's arrived_at, once. 1 = marked, 0 = unknown trip or already arrived, None = no database."""
        return self._mongo_call(lambda db: db.trips.update_one(
            {"trip_id": trip_id, "arrived_at": None}, {"$set": {"arrived_at": at}}).matched_count)

    def claim_reward(self, trip_id: str, wallet: str, route: int, at: datetime) -> dict | str | None:
        """A finished trip's route reward, claimed once: one Mongo `rewards` doc per trip (the only place a wallet
        address is stored), status "paying" until settled. The reward doc; "no_offer", "not_arrived", "wrong_route"
        or "taken" (already claimed); None = no database."""
        def q(db):
            trip = db.trips.find_one({"trip_id": trip_id})
            if not trip or not trip.get("reward_offer"):
                return "no_offer"
            if trip.get("arrived_at") is None:
                return "not_arrived"
            o = trip["reward_offer"]
            if route != o["route"]:
                return "wrong_route"
            doc = {"trip_id": trip_id, "wallet": wallet, "lamports": o["lamports"], "route": o["route"],
                   "expected_sec": o["expected_sec"], "depart_at": trip["depart_at"], "arrived_at": trip["arrived_at"],
                   "claimed_at": at, "status": "paying", "signature": None}
            if db.rewards.update_one({"trip_id": trip_id}, {"$setOnInsert": doc}, upsert=True).upserted_id is None:
                return "taken"
            return doc
        return self._mongo_call(q)

    def finish_reward(self, trip_id: str, result: dict) -> None:
        self._mongo_call(lambda db: db.rewards.update_one({"trip_id": trip_id}, {"$set": result}))


# === map views (/events window, /road-conditions, /traffic) ======================================================

Box = tuple[float, float, float, float]  # lon_min, lat_min, lon_max, lat_max

# Time-window rules the API owns (the trip-side buffers live in web/lib/context.ts).
DEFAULT_EVENT_DURATION = timedelta(hours=3)  # events with no end_time (Ticketmaster has none)
OPEN_ENDED_INCIDENT = timedelta(hours=6)     # incidents with no end_time count as active this long after start
# DataSF closure applications that aren't approved yet may never happen.
UNAPPROVED = {"Application In Review", "Submitted", "Pending Payment", "Pending Additional Information", "On Hold",
              "Denied", "Withdrawn", "Cancelled"}
INACTIVE_EVENT = {"cancelled", "postponed", "archived"}
# Curb / lane permits: thousands at any time and the road stays open. Opt-in via include_permits.
PERMIT_SOURCES = ("street_use_permits", "excavation_permits")
MAX_ITEMS = 2000


class StoreUnavailable(RuntimeError):
    """Database not configured or not reachable. The API answers 503; routing is unaffected."""


def _env_url(name: str) -> str:
    url = _url(name)
    if not url:
        raise StoreUnavailable(f"{name} is not configured")
    return url


_mongo: Any = None


def mongo_db() -> Any:
    global _mongo
    if _mongo is None:
        from pymongo import MongoClient

        client = MongoClient(_env_url("MONGODB_URI"), serverSelectionTimeoutMS=5000, tz_aware=True,
                             appname="transpeaktation-api")
        _mongo = client.get_default_database(default="transpeaktation")
    return _mongo


def tiger_conn() -> Any:
    import psycopg

    return psycopg.connect(_env_url("TIGER_DATABASE_URL"), connect_timeout=5, application_name="transpeaktation-api")


# --- geometry helpers ------------------------------------------------------------------------------------------

def _lines(geom: dict | None) -> list[list[list[float]]]:
    """GeoJSON Point / LineString / MultiLineString / MultiPoint -> list of [lon, lat] vertex lists."""
    if not geom:
        return []
    t, c = geom.get("type"), geom.get("coordinates")
    if t == "Point":
        return [[c]]
    if t in ("LineString", "MultiPoint"):
        return [c]
    if t == "MultiLineString":
        return list(c)
    return []


def _valid(lon: Any, lat: Any) -> bool:
    return isinstance(lon, (int, float)) and isinstance(lat, (int, float)) and -180 <= lon <= 180 and -90 <= lat <= 90


def rep_point(geom: dict | None) -> tuple[float, float] | None:
    """(lon, lat) to pin a shape on: the point itself, or the middle vertex of the first line."""
    lines = [ln for ln in _lines(geom) if ln]
    if not lines:
        return None
    ln = lines[0]
    lon, lat = ln[len(ln) // 2][:2]
    return (lon, lat) if _valid(lon, lat) else None


def centroid(geoms: Iterable[dict | None]) -> tuple[float, float] | None:
    pts = [p[:2] for g in geoms for ln in _lines(g) for p in ln if len(p) >= 2 and _valid(*p[:2])]
    if not pts:
        return None
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def _inside(pt: tuple[float, float] | None, box: Box) -> bool:
    return pt is not None and box[0] <= pt[0] <= box[2] and box[1] <= pt[1] <= box[3]


def _iso(t: datetime | None) -> str | None:
    if t is None:
        return None
    if t.tzinfo is None:  # Mongo without tz_aware hands back naive UTC
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _street(s: str | None) -> str | None:
    """'HUBBELL ST between 07TH ST and 16TH ST' -> 'Hubbell St between 07th St and 16th St'."""
    if not s:
        return None
    return " ".join(w if w in ("between", "and") else w.capitalize() for w in s.lower().split())


# --- events ----------------------------------------------------------------------------------------------------

EVENT_FIELDS = {"title": 1, "name": 1, "category": 1, "start_time": 1, "end_time": 1, "location": 1, "venue_id": 1,
                "venue_name": 1, "status": 1, "source_names": 1, "road_closure_ids": 1}
CLOSURE_FIELDS = {"source": 1, "source_id": 1, "category": 1, "is_closure": 1, "incident_type": 1, "location": 1,
                  "start_time": 1, "end_time": 1, "last_ingested_at": 1, "road_segment_ids": 1,
                  "details.name": 1, "details.category": 1, "details.street": 1, "details.from_street": 1,
                  "details.to_street": 1, "details.status": 1, "details.is_special_event": 1,
                  "details.call_type": 1, "details.permit_type": 1, "details.type_of_work": 1,
                  "details.location_text": 1, "details.route": 1,
                  "source_fields.case_num": 1, "source_fields.loc_desc": 1}


def _approved(doc: dict) -> bool:
    return (doc.get("details") or {}).get("status") not in UNAPPROVED


def event_from_doc(d: dict, venues: dict[str, str]) -> dict | None:
    """Canonical Mongo `events` doc (ingest/DESIGN.md §4) -> MapEvent."""
    pt = rep_point(d.get("location"))
    name = d.get("title") or d.get("name")
    if pt is None or not name or d.get("start_time") is None:
        return None
    names = d.get("source_names") or []
    return {
        "id": str(d["_id"]), "name": name, "category": d.get("category"),
        "venue": d.get("venue_name") or venues.get(d.get("venue_id") or ""),
        "lon": pt[0], "lat": pt[1], "start_time": _iso(d["start_time"]), "end_time": _iso(d.get("end_time")),
        "source": names[0] if names else "events", "status": d.get("status"),
        "road_closure_ids": [str(x) for x in d.get("road_closure_ids") or []],
    }


def events_from_closures(docs: Iterable[dict]) -> list[dict]:
    """DataSF special-event closures -> one MapEvent per permit case and start time (a street fair closes
    several blocks, one row each). ingest/DESIGN.md plans to merge these into `events`; until it does, the
    API groups them here so the map has real events."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for d in docs:
        case = (d.get("source_fields") or {}).get("case_num") or (d.get("details") or {}).get("name")
        if case and d.get("start_time") is not None:
            groups[(d["source"], str(case), d["start_time"])].append(d)
    out = []
    for (source, case, start), rows in groups.items():
        pt = centroid(r.get("location") for r in rows)
        det, sf = rows[0].get("details") or {}, rows[0].get("source_fields") or {}
        if pt is None or not det.get("name"):
            continue
        ends = [r["end_time"] for r in rows if r.get("end_time") is not None]
        venue = sf.get("loc_desc") or (f"{det['street']} between {det.get('from_street')} and {det.get('to_street')}"
                                       if det.get("street") and det.get("from_street") else det.get("street"))
        out.append({
            "id": f"{source}:{case}@{_iso(start)}", "name": det["name"], "category": "special_event",
            "venue": _street(venue) + (f" (+{len(rows) - 1} more blocks)" if len(rows) > 1 else "") if venue else None,
            "lon": pt[0], "lat": pt[1], "start_time": _iso(start), "end_time": _iso(max(ends)) if ends else None,
            "source": source, "status": det.get("status"),
            "road_closure_ids": sorted(f"{r['source']}:{r['source_id']}" for r in rows),
        })
    return out


def find_closure_events(db: Any, start: datetime, end: datetime) -> list[dict]:
    """Approved DataSF special-event closures overlapping [start, end], as MapEvents (events_from_closures)."""
    q = {"details.is_special_event": True, "start_time": {"$lte": end}, "end_time": {"$gte": start}}
    return events_from_closures(d for d in db["road_incidents"].find(q, CLOSURE_FIELDS).limit(MAX_ITEMS * 5)
                                if _approved(d))


def find_events(db: Any, start: datetime, end: datetime, box: Box) -> list[dict]:
    """Events whose time window overlaps [start, end] and whose point is inside `box`, soonest first."""
    q_events = {
        "start_time": {"$lte": end},
        "status": {"$nin": sorted(INACTIVE_EVENT)},
        "$or": [{"end_time": {"$gte": start}},
                {"end_time": None, "start_time": {"$gte": start - DEFAULT_EVENT_DURATION}}],
    }
    docs = list(db["events"].find(q_events, EVENT_FIELDS).limit(MAX_ITEMS))
    venue_ids = sorted({d["venue_id"] for d in docs if d.get("venue_id")})
    venues = {str(v["_id"]): v.get("name") for v in db["venues"].find({"_id": {"$in": venue_ids}}, {"name": 1})} \
        if venue_ids else {}
    out = [e for d in docs if (e := event_from_doc(d, venues))] + find_closure_events(db, start, end)
    out = [e for e in out if _inside((e["lon"], e["lat"]), box)]
    return sorted(out, key=lambda e: (e["start_time"], e["id"]))[:MAX_ITEMS]


# --- road conditions -------------------------------------------------------------------------------------------

def condition_from_doc(d: dict) -> dict | None:
    """Mongo `road_incidents` doc -> RoadCondition, or None when it has no usable location."""
    geom = d.get("location")
    pt = rep_point(geom)
    if pt is None:
        return None
    det = d.get("details") or {}
    return {
        "id": f"{d['source']}:{d['source_id']}", "kind": d.get("incident_type") or "incident",
        "category": d.get("category"), "is_closure": bool(d.get("is_closure")),
        "description": det.get("name") or det.get("type_of_work") or det.get("permit_type") or det.get("call_type")
        or det.get("category"),
        "street": _street(det.get("street") or det.get("location_text") or det.get("route")), "status": det.get("status"),
        "lon": pt[0], "lat": pt[1], "geometry": geom,
        "start_time": _iso(d.get("start_time")), "end_time": _iso(d.get("end_time")),
        "updated_at": _iso(d.get("last_ingested_at")), "source": d["source"],
        "road_segment_ids": list(d.get("road_segment_ids") or []),
    }


def find_road_conditions(db: Any, start: datetime, end: datetime, box: Box, include_permits: bool = False) -> list[dict]:
    """Closures / incidents active at some point in [start, end], inside `box`. Special-event closures are
    left out: /events already returns them, with their ids in road_closure_ids."""
    q = {
        "details.is_special_event": {"$ne": True},
        **({} if include_permits else {"source": {"$nin": list(PERMIT_SOURCES)}}),
        "location": {"$ne": None},
        "location_status": {"$nin": ["withheld", "unlocated"]},
        "$and": [
            {"$or": [{"start_time": {"$lte": end}}, {"start_time": None}]},
            {"$or": [{"end_time": {"$gte": start}},
                     {"end_time": None, "start_time": {"$gte": start - OPEN_ENDED_INCIDENT}}]},
        ],
    }
    out = [c for d in db["road_incidents"].find(q, CLOSURE_FIELDS).limit(MAX_ITEMS * 3)
           if _approved(d) and (c := condition_from_doc(d)) and _inside((c["lon"], c["lat"]), box)]
    return sorted(out, key=lambda c: (not c["is_closure"], c["id"]))[:MAX_ITEMS]


# --- traffic (Tiger) -------------------------------------------------------------------------------------------

# Latest reading per segment. Muni runs low (bus stops) and stays out, per AGENTS.md; TomTom (measured free flow)
# beats a Mapbox route probe, which beats a tile's congestion-only estimate.
TRAFFIC_SQL = """
SELECT DISTINCT ON (road_segment_id) road_segment_id, time, source, speed_mph, free_flow_speed_mph, congestion_ratio
FROM traffic_metrics
WHERE road_segment_id = ANY(%s) AND time >= %s AND source <> 'muni'
ORDER BY road_segment_id, time DESC,
         CASE source WHEN 'tomtom' THEN 0 WHEN 'mapbox_route' THEN 1 ELSE 2 END
"""
TRAFFIC_COLS = ("road_segment_id", "time", "source", "speed_mph", "free_flow_speed_mph", "congestion_ratio")


def find_traffic(conn: Any, segment_ids: list[str], since: datetime) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(TRAFFIC_SQL, (segment_ids, since))
        rows = cur.fetchall()
    return [{**dict(zip(TRAFFIC_COLS, r)), "time": _iso(r[1])} for r in rows]
