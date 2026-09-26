"""Read-only views of what ingest/ writes: Mongo `events` + `road_incidents`, Tiger `traffic_metrics`.

Shapes follow contracts/map_context.schema.json. Only those fields leave the API: no raw source rows, no
provenance, no credentials. Everything here is blocking (pymongo / psycopg); main.py calls it in a thread.
"""
from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

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
    url = (os.environ.get(name) or "").strip()
    if not url or "<password>" in url:
        raise StoreUnavailable(f"{name} is not configured")
    return url


def configured(name: str) -> bool:
    try:
        return bool(_env_url(name))
    except StoreUnavailable:
        return False


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
    out = [e for d in docs if (e := event_from_doc(d, venues))]

    q_closures = {"details.is_special_event": True, "start_time": {"$lte": end}, "end_time": {"$gte": start}}
    closures = [d for d in db["road_incidents"].find(q_closures, CLOSURE_FIELDS).limit(MAX_ITEMS * 5) if _approved(d)]
    out += events_from_closures(closures)
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
