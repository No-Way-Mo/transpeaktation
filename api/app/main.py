"""transPEAKtation API: place search + traffic-aware routes with OSM road-segment IDs.

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
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

_API_DIR = Path(__file__).resolve().parent.parent
load_dotenv(_API_DIR / ".env")  # api/.env; real env vars win
# Local dev: reuse keys already in ingest/.env (e.g. its MAPBOX_TOKEN) instead of copying them. Never overrides.
load_dotenv(_API_DIR.parent / "ingest" / ".env")

from . import providers
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
    allow_methods=["GET"],
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


@app.get("/health")
def health():
    if not os.environ.get("MAPBOX_TOKEN"):
        mapbox = "no token (using OSRM/Nominatim)"
    else:
        mapbox = "ready" if providers.mapbox_available() else "backing off after an error"
    return {"ok": True, "mapbox": mapbox, "road_graph": segments.status}
