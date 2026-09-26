"""Optional text geocoding for records that have NO usable location.

Off unless GEOCODER=mapbox is set in ingest/.env. It then uses the team's MAPBOX_TOKEN
(same token as `python -m pull.poll`; Mapbox was chosen over Google, TODO.md). Requests
ask for permanent geocoding because results are stored in MongoDB (Mapbox terms).
Results are cached in ingest/data/cache/geocode.json so reruns are stable and cheap.
Only query text is sent; records that already have coordinates are never geocoded.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol

from pull.http import FetchError, fetch

from .geom import BAY_BBOX, valid_lonlat

Coord = tuple[float, float]


class Geocoder(Protocol):
    name: str

    def geocode(self, query: str) -> Coord | None: ...


class MapboxGeocoder:
    name = "mapbox"
    URL = "https://api.mapbox.com/search/geocode/v6/forward"

    def __init__(self, token: str):
        self.token = token

    def geocode(self, query: str) -> Coord | None:
        body = fetch(self.URL, params={"q": query, "access_token": self.token, "limit": "1", "permanent": "true",
                                       "bbox": ",".join(map(str, BAY_BBOX))}, retries=2)
        feats = json.loads(body).get("features") or []
        if not feats:
            return None
        lon, lat = feats[0]["geometry"]["coordinates"][:2]
        return float(lon), float(lat)


class CachedGeocoder:
    """Wraps a provider: caches answers (incl. misses), never raises, keeps counts."""

    def __init__(self, provider: Geocoder, cache_path: Path | None = None):
        self.provider = provider
        self.name = provider.name
        self.cache_path = cache_path
        self.cache: dict[str, list[float] | None] = {}
        self.calls = self.failures = 0
        if cache_path and cache_path.is_file():
            try:
                self.cache = json.loads(cache_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.cache = {}

    def geocode(self, query: str) -> Coord | None:
        key = f"{self.name}|{' '.join(query.lower().split())}"
        if key not in self.cache:
            self.calls += 1
            try:
                hit = self.provider.geocode(query)
            except (FetchError, KeyError, ValueError, TypeError, IndexError):
                self.failures += 1
                return None  # transient: don't cache
            ok = hit and valid_lonlat(*hit) and BAY_BBOX[0] <= hit[0] <= BAY_BBOX[2] and BAY_BBOX[1] <= hit[1] <= BAY_BBOX[3]
            self.cache[key] = [hit[0], hit[1]] if ok else None
        v = self.cache[key]
        return (v[0], v[1]) if v else None

    def save(self) -> None:
        if self.cache_path:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self.cache, indent=0, sort_keys=True), encoding="utf-8")


def from_env(cache_path: Path | None = None) -> tuple[CachedGeocoder | None, str]:
    """(geocoder or None, human-readable reason)."""
    choice = (os.environ.get("GEOCODER") or "").strip().lower()
    if choice in ("", "none"):
        return None, "geocoding off (set GEOCODER=mapbox in ingest/.env to enable)"
    if choice != "mapbox":
        return None, f"geocoding off: unknown GEOCODER={choice!r} (supported: mapbox)"
    token = os.environ.get("MAPBOX_TOKEN")
    if not token:
        return None, "geocoding skipped: GEOCODER=mapbox but MAPBOX_TOKEN is not set"
    return CachedGeocoder(MapboxGeocoder(token), cache_path), "mapbox"
