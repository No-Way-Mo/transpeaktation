"""transPEAKtation API: place search, traffic-aware routes with OSM road-segment IDs, the event-aware trip plan
(routes + what ingest/ stored + the model), voice → trip intent.

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


def _utc(iso_z: str | None) -> datetime | None:
    return datetime.strptime(iso_z, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) if iso_z else None


def _near_any(ev: dict, found: list[dict], radius_m: float = 700) -> bool:
    return any(model.meters(c, (ev["lat"], ev["lon"])) <= radius_m for r in found for c in r["coords"][::3])


@app.get("/plan")
async def plan_trip(
    background: BackgroundTasks,
    from_: str = Query(alias="from", description="Start as 'lon,lat'"),
    to: str = Query(description="Destination as 'lon,lat'"),
    depart_at: str | None = Query(None, description="Leave at (ISO 8601 with offset); omit to leave now"),
    arrive_by: str | None = Query(None, description="Arrive by (ISO 8601 with offset)"),
):
    """The trip planner: candidate routes (Mapbox/OSRM) -> events, closures, live traffic and forecasts for their
    road segments (Mongo / Tiger, written by ingest/ and ml/) -> event-aware model -> pick, explanation and a
    better departure time. Logs the request to Mongo `trips` (no user identity)."""
    got = await routes(from_, to, depart_at, arrive_by)
    found, now = got["routes"], datetime.now(timezone.utc)
    dep, arr = _utc(when(depart_at)), _utc(when(arrive_by))
    mode = "arrive" if arr else "depart" if dep else "now"
    departs = [arr - timedelta(seconds=r["dur"]) if arr else max(dep or now, now) for r in found]
    t0 = min(departs)
    t1 = max(d + timedelta(seconds=r["dur"]) for d, r in zip(departs, found)) + timedelta(minutes=90)  # + advice range
    sids = sorted({s for r in found for s in (r.get("road_segment_ids") or [])})

    events, incidents, traffic, predictions, lengths = await asyncio.gather(
        asyncio.to_thread(store.events_between, t0 - timedelta(hours=1), t1),
        asyncio.to_thread(store.incidents_on, sids, t0, t1),
        asyncio.to_thread(store.traffic_latest, sids),
        asyncio.to_thread(store.predictions, sids, t0, t1),
        asyncio.to_thread(segments.lengths, sids))
    evs = [e for e in (model.from_mongo(x) for x in events or []) if e] if events is not None else \
        model.demo_events(t0)
    ctx = {"events": evs, "incidents": incidents or [], "traffic": traffic or [], "predictions": predictions or [],
           "lengths": lengths}
    result = model.plan(found, departs, mode, ctx, now=now)
    best = result["preds"][result["best"]]

    a, b = lonlat(from_), lonlat(to)
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
        "data": {"events": "mongo" if events is not None else "demo",
                 "incidents": "mongo" if incidents is not None else "unavailable",
                 "traffic": "tiger" if traffic is not None else "unavailable",
                 "predictions": "tiger" if predictions else "none (event-impact heuristic)"},
    }


@app.get("/events")
async def events_today(date: str | None = Query(None, description="YYYY-MM-DD, San Francisco local; default today")):
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


@app.get("/health")
def health():
    if not os.environ.get("MAPBOX_TOKEN"):
        mapbox = "no token (using OSRM/Nominatim)"
    else:
        mapbox = "ready" if providers.mapbox_available() else "backing off after an error"
    return {"ok": True, "mapbox": mapbox, "road_graph": segments.status, **store.status(),
            "voice": "ready" if voice.available() else "no ELEVENLABS_API_KEY"}
