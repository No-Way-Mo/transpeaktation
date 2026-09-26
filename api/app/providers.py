"""Place search + driving routes. Mapbox first (live traffic); OSRM / Nominatim when Mapbox is
unavailable. Everything is normalized to the shapes web/lib/route.ts already renders."""
from __future__ import annotations

import os
import time
from typing import Any

import httpx

SF_BBOX = (-122.53, 37.70, -122.35, 37.84)  # lon_min, lat_min, lon_max, lat_max
SF_CENTER = (-122.4075, 37.788)
UA = {"User-Agent": "transPEAKtation/0.1 (ShellHacks 2026 demo)"}  # Nominatim's policy requires an identifying UA

Place = dict[str, Any]
Route = dict[str, Any]
LonLat = tuple[float, float]


class ProviderError(Exception):
    pass


class NoRoute(ProviderError):
    """The provider answered fine; there is just no drivable route (water, closed area)."""


# ponytail: one process-wide switch. After Mapbox refuses (bad token, quota, outage) we stop calling it for a
# minute instead of burning the shared free tier on retries. Per-worker state; fine for one uvicorn process.
_mapbox_off_until = 0.0


def _token() -> str | None:
    return os.environ.get("MAPBOX_TOKEN") or None


def mapbox_available() -> bool:
    return bool(_token()) and time.monotonic() >= _mapbox_off_until


def _mapbox_failed(status: int | None) -> None:
    global _mapbox_off_until
    # 401/403 = token problem, 429 = quota; both won't fix themselves in seconds.
    _mapbox_off_until = time.monotonic() + (300 if status in (401, 403, 429) else 60)


async def _get(client: httpx.AsyncClient, url: str, params: dict, **kw) -> Any:
    try:
        r = await client.get(url, params=params, timeout=8, **kw)
    except httpx.HTTPError as e:
        raise ProviderError(f"{url}: {type(e).__name__}") from e
    if r.status_code != 200:
        if r.status_code == 400 and r.headers.get("content-type", "").startswith("application/json") \
                and r.json().get("code") == "NoRoute":  # OSRM reports "no route" as a 400
            raise NoRoute("no route")
        err = ProviderError(f"{url}: HTTP {r.status_code}")
        err.status = r.status_code  # type: ignore[attr-defined]
        raise err
    return r.json()


# --- places ------------------------------------------------------------------

def mapbox_places(data: dict) -> list[Place]:
    out = []
    for f in data.get("features", []):
        p, (lon, lat) = f.get("properties", {}), f["geometry"]["coordinates"]
        out.append({"label": p.get("name") or p.get("full_address", ""), "sub": p.get("place_formatted", ""),
                    "lat": lat, "lon": lon})
    return out


def nominatim_places(data: list) -> list[Place]:
    out = []
    for d in data:
        parts = d["display_name"].split(", ")
        out.append({"label": d.get("name") or parts[0], "sub": ", ".join(parts[1:4]),
                    "lat": float(d["lat"]), "lon": float(d["lon"])})
    return out


async def search_places(client: httpx.AsyncClient, q: str) -> tuple[list[Place], str]:
    bbox = ",".join(map(str, SF_BBOX))
    if mapbox_available():
        try:
            data = await _get(client, "https://api.mapbox.com/search/searchbox/v1/forward", {
                "q": q, "limit": 5, "bbox": bbox, "proximity": f"{SF_CENTER[0]},{SF_CENTER[1]}",
                "language": "en", "access_token": _token()})
        except ProviderError as e:
            _mapbox_failed(getattr(e, "status", None))
        else:
            return mapbox_places(data), "mapbox"
    lon0, lat0, lon1, lat1 = SF_BBOX
    data = await _get(client, "https://nominatim.openstreetmap.org/search", {
        "format": "json", "limit": 5, "bounded": 1, "viewbox": f"{lon0},{lat1},{lon1},{lat0}", "q": q}, headers=UA)
    return nominatim_places(data), "nominatim"


# --- routes ------------------------------------------------------------------

def _step(s: dict) -> dict:
    m = s["maneuver"]
    return {"distance": s["distance"], "duration": s["duration"], "name": s.get("name", ""),
            "maneuver": {"type": m["type"], "modifier": m.get("modifier"), "location": m["location"]}}


def normalize_routes(data: dict) -> list[Route]:
    """Mapbox Directions and OSRM share the OSRM response format; Mapbox adds typical duration + congestion."""
    if data.get("code") == "NoRoute" or (data.get("code") == "Ok" and not data.get("routes")):
        raise NoRoute(data.get("message") or "no route")
    if data.get("code") != "Ok":
        raise ProviderError(data.get("message") or data.get("code") or "bad response")
    out = []
    for r in data["routes"]:
        leg = r["legs"][0]
        out.append({
            "dur": r["duration"],
            "dur_typical": r.get("duration_typical"),          # Mapbox driving-traffic only
            "dist": r["distance"],
            "summary": leg.get("summary", ""),
            "coords": [[lat, lon] for lon, lat in r["geometry"]["coordinates"]],
            "congestion": leg.get("annotation", {}).get("congestion"),  # one level per coords pair, Mapbox only
            "steps": [_step(s) for s in leg["steps"]],
        })
    return out


async def find_routes(client: httpx.AsyncClient, a: LonLat, b: LonLat) -> tuple[list[Route], str]:
    coords = f"{a[0]},{a[1]};{b[0]},{b[1]}"
    common = {"alternatives": "true", "geometries": "geojson", "overview": "full", "steps": "true"}
    if mapbox_available():
        try:
            data = await _get(client, f"https://api.mapbox.com/directions/v5/mapbox/driving-traffic/{coords}",
                              {**common, "annotations": "congestion", "access_token": _token()})
        except ProviderError as e:  # transport/HTTP failure only; a valid "NoRoute" answer is not Mapbox's fault
            _mapbox_failed(getattr(e, "status", None))
        else:
            return normalize_routes(data), "mapbox"
    data = await _get(client, f"https://router.project-osrm.org/route/v1/driving/{coords}",
                      {**common, "alternatives": "3"}, headers=UA)
    return normalize_routes(data), "osrm"
