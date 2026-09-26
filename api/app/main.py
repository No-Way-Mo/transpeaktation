"""transPEAKtation API: place search, traffic-aware routes with OSM road-segment IDs, the event-aware trip plan
(routes + what ingest/ stored + the model), voice → trip intent, and read-only views of ingested data (events,
road conditions, segment traffic) from Mongo / Tiger.

    cd api && .venv/bin/uvicorn app.main:app --reload    # http://localhost:8000/docs
"""
from __future__ import annotations

import asyncio
import os
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware

_API_DIR = Path(__file__).resolve().parent.parent
load_dotenv(_API_DIR / ".env")  # api/.env; real env vars win
# Local dev: reuse keys already in ingest/.env (e.g. its MAPBOX_TOKEN) instead of copying them. Never overrides.
load_dotenv(_API_DIR.parent / "ingest" / ".env")

from . import model, providers, voice
from . import store as ingested  # map views (find_*); `store` below is the planner's Store
from .segments import Segments
from .store import Store

# Accept a little beyond the SF search box so Treasure Island / Daly City edges still route.
SERVICE_AREA = (-122.62, 37.60, -122.28, 37.93)  # lon_min, lat_min, lon_max, lat_max
segments = Segments()
store = Store()
state: dict[str, Any] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    state["http"] = httpx.AsyncClient()
    threading.Thread(target=segments.load, daemon=True).start()  # routes work while the graph loads
    yield
    await state["http"].aclose()


app = FastAPI(title="transPEAKtation API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000").split(",") if o.strip()],
    allow_methods=["GET", "POST"],
)

# ponytail: in-process TTL cache, cleared wholesale when it grows. Protects the shared Mapbox quota from
# repeat lookups (typing, re-renders, swap). One uvicorn worker only; upgrade to Redis if we scale out.
_cache: dict[tuple, tuple[float, Any]] = {}


def _cached(key: tuple) -> Any:
    hit = _cache.get(key)
    return hit[1] if hit and hit[0] > time.monotonic() else None


def _store(key: tuple, ttl: float, value: Any) -> Any:
    if len(_cache) > 2000:
        _cache.clear()
    _cache[key] = (time.monotonic() + ttl, value)
    return value


def lonlat(raw: str) -> tuple[float, float]:
    try:
        lon, lat = (float(x) for x in raw.split(","))
    except ValueError:
        raise HTTPException(400, "expected 'lon,lat'")
    lon0, lat0, lon1, lat1 = SERVICE_AREA
    if not (lon0 <= lon <= lon1 and lat0 <= lat <= lat1):  # also rejects nan/inf
        raise HTTPException(400, "outside the San Francisco service area")
    return lon, lat


REPLAY_MAX = timedelta(days=365)


def when(raw: str | None, replay: bool = False) -> datetime | None:
    """ISO time with offset -> UTC. Now to 7 days out (a few minutes of slack; earlier = now).
    replay (a simulated past trip) also allows up to a year back, and keeps the past time."""
    if raw is None:
        return None
    try:
        t = datetime.fromisoformat(raw)
    except ValueError:
        raise HTTPException(400, "expected an ISO 8601 time, e.g. 2026-09-26T19:00:00-07:00")
    if t.tzinfo is None:
        raise HTTPException(400, "time needs a UTC offset")
    now = datetime.now(timezone.utc)
    if not now - (REPLAY_MAX if replay else timedelta(minutes=5)) <= t <= now + timedelta(days=7):
        raise HTTPException(400, "time must be between now and 7 days from now"
                                 + (" (or up to a year back)" if replay else ", or pass replay=true for a past trip"))
    t = t.astimezone(timezone.utc)
    return t if replay else max(t, now)


def mapbox_time(t: datetime | None, now: datetime) -> str | None:
    """Mapbox's UTC form. Mapbox only predicts ahead, so a past time asks for the same SF weekday and clock time
    in the coming week: its typical traffic repeats weekly. (The observed traffic of that day comes from Tiger.)"""
    if t is None:
        return None
    while t < now:
        t = (t.astimezone(model.SF_TZ) + timedelta(weeks=1)).astimezone(timezone.utc)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


@app.get("/places")
async def places(q: str = Query(min_length=1, max_length=120, description="Search text")):
    q = " ".join(q.split())
    if not q:
        raise HTTPException(400, "empty query")
    key = ("places", q.lower())
    if (hit := _cached(key)) is not None:
        return hit
    try:
        found, source = await providers.search_places(state["http"], q)
    except providers.ProviderError:
        raise HTTPException(502, "place search unavailable")
    return _store(key, 600, {"places": found, "source": source})


@app.get("/routes")
async def routes(
    from_: str = Query(alias="from", description="Start as 'lon,lat'"),
    to: str = Query(description="Destination as 'lon,lat'"),
    depart_at: str | None = Query(None, description="Leave at (ISO 8601 with offset); omit for live traffic now"),
    arrive_by: str | None = Query(None, description="Arrive by (ISO 8601 with offset)"),
):
    a, b = lonlat(from_), lonlat(to)
    if depart_at and arrive_by:
        raise HTTPException(400, "pass depart_at or arrive_by, not both")
    now = datetime.now(timezone.utc)
    return await _routes(a, b, mapbox_time(when(depart_at), now), mapbox_time(when(arrive_by), now))


async def _routes(a: tuple[float, float], b: tuple[float, float], dep: str | None, arr: str | None) -> dict:
    # ~10 m, to the minute: nearby taps / re-renders share a cached answer
    key = ("routes", *(round(x, 4) for x in (*a, *b)), dep and dep[:16], arr and arr[:16])
    if (hit := _cached(key)) is not None:
        return hit
    try:
        found, source = await providers.find_routes(state["http"], a, b, dep, arr)
    except providers.NoRoute:
        raise HTTPException(404, "no drivable route between these points")
    except providers.ProviderError:
        raise HTTPException(502, "routing unavailable")
    for r in found:
        r["road_segment_ids"] = await asyncio.to_thread(segments.match, r["coords"])
    # Short TTL: Mapbox ETAs include live traffic.
    return _store(key, 60, {"routes": found, "source": source})


def _near_any(ev: dict, found: list[dict], radius_m: float = 700) -> bool:
    return any(model.meters(c, (ev["lat"], ev["lon"])) <= radius_m for r in found for c in r["coords"][::3])


@app.get("/plan")
async def plan_trip(
    background: BackgroundTasks,
    from_: str = Query(alias="from", description="Start as 'lon,lat'"),
    to: str = Query(description="Destination as 'lon,lat'"),
    depart_at: str | None = Query(None, description="Leave at (ISO 8601 with offset); omit to leave now"),
    arrive_by: str | None = Query(None, description="Arrive by (ISO 8601 with offset)"),
    replay: bool = Query(False, description="Simulate a trip at a past time with the data stored for then (demo); "
                                            "not logged as a trip"),
):
    """The trip planner: candidate routes (Mapbox/OSRM) -> events, closures, traffic and forecasts for their road
    segments at the trip's time (Mongo / Tiger, written by ingest/ and ml/) -> event-aware model -> pick,
    explanation and a better departure time. Logs the request to Mongo `trips` (no user identity).
    Traffic by trip time: live (now), observed (past, replay), typical (future); see Store.traffic_at."""
    a, b = lonlat(from_), lonlat(to)
    if depart_at and arrive_by:
        raise HTTPException(400, "pass depart_at or arrive_by, not both")
    real_now = datetime.now(timezone.utc)
    dep, arr = when(depart_at, replay), when(arrive_by, replay)
    got = await _routes(a, b, mapbox_time(dep, real_now), mapbox_time(arr, real_now))
    found = got["routes"]
    mode = "arrive" if arr else "depart" if dep else "now"
    departs = [arr - timedelta(seconds=r["dur"]) if arr else dep or real_now for r in found]
    t0 = min(departs)
    # A replayed trip runs as if it were then: the model treats that day's observed traffic as live.
    now = min(t0, real_now) if replay else real_now
    t1 = max(d + timedelta(seconds=r["dur"]) for d, r in zip(departs, found)) + timedelta(minutes=90)  # + advice range
    sids = sorted({s for r in found for s in (r.get("road_segment_ids") or [])})

    events, incidents, (traffic, traffic_kind), predictions, lengths = await asyncio.gather(
        asyncio.to_thread(store.events_between, t0 - timedelta(hours=1), t1),
        asyncio.to_thread(store.incidents_on, sids, t0, t1),
        asyncio.to_thread(store.traffic_at, sids, t0, real_now),
        asyncio.to_thread(store.predictions, sids, t0, t1),
        asyncio.to_thread(segments.lengths, sids))
    evs = [e for e in (model.from_mongo(x) for x in events or []) if e] if events is not None else \
        model.demo_events(t0)
    ctx = {"events": evs, "incidents": incidents or [], "traffic": traffic or [], "traffic_kind": traffic_kind,
           "predictions": predictions or [], "lengths": lengths}
    result = model.plan(found, departs, mode, ctx, now=now)
    best = result["preds"][result["best"]]

    if not replay:  # a simulation isn't demand
        background.add_task(store.save_trip, {
            "requested_at": now, "source": "web", "mode": mode, "depart_at": departs[result["best"]],
            # ~100 m: enough for demand by area, without storing exact addresses
            "origin": {"lon": round(a[0], 3), "lat": round(a[1], 3)}, "destination": {"lon": round(b[0], 3), "lat": round(b[1], 3)},
            "provider": got["source"], "route_count": len(found), "picked": result["best"],
            "predicted_sec": [round(p["dur"]) for p in result["preds"]], "baseline_sec": [round(r["dur"]) for r in found],
            "event_ids": [h["id"] for h in best["event_hits"]], "blocked": best["blocked"], "model": best["model"]})
    return {
        "routes": found, "source": got["source"], "plan": result,
        "events": [model.event_view(e) for e in evs if _near_any(e, found)],
        "data": {"at": t0.isoformat(), "replay": replay,  # the moment the inputs describe
                 "events": "mongo" if events is not None else "demo",
                 "incidents": "mongo" if incidents is not None else "unavailable",
                 "traffic": f"tiger:{traffic_kind}" if traffic is not None else "unavailable",
                 "predictions": "tiger" if predictions else "none (event-impact heuristic)"},
    }


async def _resolve(query: str | None) -> dict | None:
    """Spoken place name -> {query, place}. place is the top search hit, or None if nothing matched."""
    if not query:
        return None
    try:
        found = await places(query)
    except HTTPException:
        found = {"places": []}
    return {"query": query, "place": (found["places"] or [None])[0]}


@app.post("/voice")
async def voice_intent(audio: UploadFile = File(description="Recorded speech (webm, m4a, wav, ...)")):
    """Speech -> trip intent. Plans only: the app must still ask the user to confirm any booking."""
    if not voice.available():
        raise HTTPException(503, "voice unavailable (no ELEVENLABS_API_KEY)")
    data = await audio.read(voice.MAX_AUDIO_BYTES + 1)
    if not data:
        raise HTTPException(400, "empty audio")
    if len(data) > voice.MAX_AUDIO_BYTES:
        raise HTTPException(413, "audio too long")
    try:
        text = await voice.transcribe(state["http"], data, audio.filename or "audio", audio.content_type or "application/octet-stream")
    except providers.ProviderError:
        raise HTTPException(502, "speech-to-text unavailable")
    intent = voice.parse_intent(text)
    dest, origin = await asyncio.gather(_resolve(intent["destination"]), _resolve(intent["origin"]))
    return {"transcript": text, **intent, "destination": dest, "origin": origin}


MAX_WINDOW = timedelta(days=14)


def window(start: str, end: str) -> tuple[datetime, datetime]:
    try:
        a, b = datetime.fromisoformat(start), datetime.fromisoformat(end)
    except ValueError:
        raise HTTPException(400, "expected ISO 8601 times, e.g. 2026-09-26T19:00:00-07:00")
    if a.tzinfo is None or b.tzinfo is None:
        raise HTTPException(400, "times need a UTC offset")
    if not timedelta(0) <= b - a <= MAX_WINDOW:
        raise HTTPException(400, "end must be after start, at most 14 days later")
    return a.astimezone(timezone.utc), b.astimezone(timezone.utc)


def bbox(raw: str | None) -> ingested.Box:
    if raw is None:
        return SERVICE_AREA
    try:
        box = tuple(float(x) for x in raw.split(","))
    except ValueError:
        box = ()
    if len(box) != 4 or not (box[0] < box[2] and box[1] < box[3]):
        raise HTTPException(400, "expected bbox 'lon_min,lat_min,lon_max,lat_max'")
    return box  # type: ignore[return-value]


async def _read(key: tuple, fn, *args) -> Any:
    """Cached, threaded DB read. A missing or unreachable database is a 503, never a crash: routing doesn't need it."""
    if (hit := _cached(key)) is not None:
        return hit
    try:
        return _store(key, 60, await asyncio.to_thread(fn, *args))
    except ingested.StoreUnavailable as e:
        raise HTTPException(503, f"ingested data unavailable: {e}")
    except Exception as e:  # driver errors (timeouts, auth) carry connection details; don't echo them
        raise HTTPException(503, f"ingested data unavailable ({type(e).__name__})")


def _mongo_read(fn, a: datetime, b: datetime, box: ingested.Box, *extra) -> list[dict]:
    return fn(ingested.mongo_db(), a, b, box, *extra)


# Windows are rounded out to 5 minutes for the cache key: "now" moves every request.
def _key(name: str, a: datetime, b: datetime, box: ingested.Box) -> tuple:
    r = lambda t: int(t.timestamp() // 300)
    return (name, r(a), r(b), box)


@app.get("/events")
async def events(
    start: str | None = Query(None, description="Window start (ISO 8601 with offset); pass with end"),
    end: str | None = Query(None, description="Window end (ISO 8601 with offset); pass with start"),
    bbox_: str | None = Query(None, alias="bbox", description="With start/end: 'lon_min,lat_min,lon_max,lat_max'; default SF"),
    date: str | None = Query(None, description="Without start/end: YYYY-MM-DD, San Francisco local; default today"),
):
    """Two views of events:
    - start + end (map pins, route context): ingested events (Mongo `events`, plus DataSF special-event street
      closures) overlapping the window, as contracts/map_context.schema.json MapEvents. 503 without Mongo.
    - otherwise (search suggestions: drop-offs, "leave at"): one SF day's events, demo events until ingest fills
      Mongo `events`."""
    if start is None and end is None:
        return await events_today(date)
    if start is None or end is None:
        raise HTTPException(400, "pass both start and end")
    if date is not None:
        raise HTTPException(400, "pass date or start/end, not both")
    a, b = window(start, end)
    box = bbox(bbox_)
    found = await _read(_key("events", a, b, box), _mongo_read, ingested.find_events, a, b, box)
    return {"events": found}


async def events_today(date: str | None) -> dict:
    """Events for the search suggestions (drop-offs, "leave at"). Demo events until ingest fills Mongo `events`."""
    try:
        day = datetime.fromisoformat(date).replace(tzinfo=model.SF_TZ) if date else datetime.now(model.SF_TZ)
    except ValueError:
        raise HTTPException(400, "expected YYYY-MM-DD")
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    key = ("events", start.date().isoformat())
    if (hit := _cached(key)) is not None:
        return hit
    found = await asyncio.to_thread(store.events_between, start, start + timedelta(days=1))
    evs = [e for e in (model.from_mongo(x) for x in found or []) if e] if found is not None else model.demo_events(start)
    return _store(key, 300, {"events": [model.event_view(e) for e in evs], "source": "mongo" if found is not None else "demo"})


@app.get("/road-conditions")
async def road_conditions(
    start: str = Query(description="Window start (ISO 8601 with offset)"),
    end: str = Query(description="Window end (ISO 8601 with offset)"),
    bbox_: str | None = Query(None, alias="bbox", description="'lon_min,lat_min,lon_max,lat_max'; default SF"),
    include_permits: bool = Query(False, description="Also return street-use / excavation permits (road stays open)"),
):
    """Ingested closures and incidents (Mongo `road_incidents`) active during the window."""
    a, b = window(start, end)
    box = bbox(bbox_)
    found = await _read((*_key("conditions", a, b, box), include_permits), _mongo_read, ingested.find_road_conditions,
                        a, b, box, include_permits)
    return {"road_conditions": found}


MAX_SEGMENTS = 400
TRAFFIC_MAX_AGE = timedelta(minutes=30)


def _tiger_traffic(ids: list[str], since: datetime) -> list[dict]:
    conn = ingested.tiger_conn()
    try:
        return ingested.find_traffic(conn, ids, since)
    finally:
        conn.close()


@app.get("/traffic")
async def traffic(segments_: str = Query(alias="segments", description="Comma-separated road_segment_ids (u-v-key)")):
    """Latest observed speed / congestion per road segment (Tiger `traffic_metrics`, last 30 min)."""
    ids = sorted({s for s in segments_.split(",") if s.strip()})
    if not ids or len(ids) > MAX_SEGMENTS:
        raise HTTPException(400, f"pass 1 to {MAX_SEGMENTS} segment ids")
    since = datetime.now(timezone.utc) - TRAFFIC_MAX_AGE
    found = await _read(("traffic", tuple(ids), int(since.timestamp() // 300)), _tiger_traffic, ids, since)
    return {"traffic": found}


@app.get("/health")
def health():
    if not os.environ.get("MAPBOX_TOKEN"):
        mapbox = "no token (using OSRM/Nominatim)"
    else:
        mapbox = "ready" if providers.mapbox_available() else "backing off after an error"
    return {"ok": True, "mapbox": mapbox, "road_graph": segments.status, **store.status(),
            "voice": "ready" if voice.available() else "no ELEVENLABS_API_KEY"}
