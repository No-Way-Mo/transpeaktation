"""transPEAKtation API: place search + traffic-aware routes with OSM road-segment IDs; voice → trip intent; read-only
views of ingested data (events, road conditions, segment traffic) from Mongo / Tiger.

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
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware

_API_DIR = Path(__file__).resolve().parent.parent
load_dotenv(_API_DIR / ".env")  # api/.env; real env vars win
# Local dev: reuse keys already in ingest/.env (e.g. its MAPBOX_TOKEN) instead of copying them. Never overrides.
load_dotenv(_API_DIR.parent / "ingest" / ".env")

from . import providers, store, voice
from .segments import Segments

# Accept a little beyond the SF search box so Treasure Island / Daly City edges still route.
SERVICE_AREA = (-122.62, 37.60, -122.28, 37.93)  # lon_min, lat_min, lon_max, lat_max
segments = Segments()
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


def when(raw: str | None) -> str | None:
    """ISO time with offset → Mapbox's UTC form. Must be from now to 7 days out (a few minutes of slack)."""
    if raw is None:
        return None
    try:
        t = datetime.fromisoformat(raw)
    except ValueError:
        raise HTTPException(400, "expected an ISO 8601 time, e.g. 2026-09-26T19:00:00-07:00")
    if t.tzinfo is None:
        raise HTTPException(400, "time needs a UTC offset")
    now = datetime.now(timezone.utc)
    if not now - timedelta(minutes=5) <= t <= now + timedelta(days=7):
        raise HTTPException(400, "time must be between now and 7 days from now")
    return max(t, now).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
    dep, arr = when(depart_at), when(arrive_by)
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


def bbox(raw: str | None) -> store.Box:
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
    except store.StoreUnavailable as e:
        raise HTTPException(503, f"ingested data unavailable: {e}")
    except Exception as e:  # driver errors (timeouts, auth) carry connection details; don't echo them
        raise HTTPException(503, f"ingested data unavailable ({type(e).__name__})")


def _mongo_read(fn, a: datetime, b: datetime, box: store.Box, *extra) -> list[dict]:
    return fn(store.mongo_db(), a, b, box, *extra)


# Windows are rounded out to 5 minutes for the cache key: "now" moves every request.
def _key(name: str, a: datetime, b: datetime, box: store.Box) -> tuple:
    r = lambda t: int(t.timestamp() // 300)
    return (name, r(a), r(b), box)


@app.get("/events")
async def events(
    start: str = Query(description="Window start (ISO 8601 with offset)"),
    end: str = Query(description="Window end (ISO 8601 with offset)"),
    bbox_: str | None = Query(None, alias="bbox", description="'lon_min,lat_min,lon_max,lat_max'; default SF"),
):
    """Ingested events (Mongo `events`, plus DataSF special-event street closures) overlapping the window."""
    a, b = window(start, end)
    box = bbox(bbox_)
    found = await _read(_key("events", a, b, box), _mongo_read, store.find_events, a, b, box)
    return {"events": found}


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
    found = await _read((*_key("conditions", a, b, box), include_permits), _mongo_read, store.find_road_conditions,
                        a, b, box, include_permits)
    return {"road_conditions": found}


MAX_SEGMENTS = 400
TRAFFIC_MAX_AGE = timedelta(minutes=30)


def _tiger_traffic(ids: list[str], since: datetime) -> list[dict]:
    conn = store.tiger_conn()
    try:
        return store.find_traffic(conn, ids, since)
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
    configured = lambda name: "configured" if store.configured(name) else "not configured"
    return {"ok": True, "mapbox": mapbox, "road_graph": segments.status,
            "voice": "ready" if voice.available() else "no ELEVENLABS_API_KEY",
            "mongo": configured("MONGODB_URI"), "tiger": configured("TIGER_DATABASE_URL")}
