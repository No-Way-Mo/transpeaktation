"""Web-mercator tile math + Mapbox Vector Tile decoding for traffic tiles."""
from __future__ import annotations

import gzip
import hashlib
import math
from typing import Any, Iterator

from .feeds import SF_BBOX

LonLat = tuple[float, float]


def lonlat_to_tile(lon: float, lat: float, z: int) -> tuple[int, int]:
    n = 2 ** z
    return int((lon + 180) / 360 * n), int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)


def tiles_for_bbox(bbox: tuple[float, float, float, float] = SF_BBOX, z: int = 13) -> list[tuple[int, int, int]]:
    x0, y0 = lonlat_to_tile(bbox[0], bbox[3], z)  # north-west corner
    x1, y1 = lonlat_to_tile(bbox[2], bbox[1], z)  # south-east corner
    return [(z, x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]


def tile_point_to_lonlat(z: int, x: int, y: int, px: float, py: float, extent: int) -> LonLat:
    """(px, py) in tile units with y pointing down -> (lon, lat)."""
    n = 2 ** z
    lon = (x + px / extent) / n * 360 - 180
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + py / extent) / n))))
    return round(lon, 6), round(lat, 6)


def decode_lines(data: bytes, z: int, x: int, y: int, layer: str) -> Iterator[tuple[list[LonLat], dict[str, Any]]]:
    """Yield (line coordinates, properties) for every line in a vector tile layer."""
    import mapbox_vector_tile  # optional dependency: pip install -e .[live]

    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    decoded = mapbox_vector_tile.decode(data, default_options={"y_coord_down": True})
    lyr = decoded.get(layer)
    if not lyr:
        return
    extent = lyr.get("extent", 4096)
    for feat in lyr["features"]:
        geom = feat["geometry"]
        parts = geom["coordinates"] if geom["type"] == "MultiLineString" else [geom["coordinates"]] \
            if geom["type"] == "LineString" else []
        for part in parts:
            yield [tile_point_to_lonlat(z, x, y, px, py, extent) for px, py in part], feat["properties"]


def line_key(coords: list[LonLat]) -> str:
    """Stable id for a road line across polls (tiles regroup lines as speeds change)."""
    return hashlib.sha1(";".join(f"{lon:.5f},{lat:.5f}" for lon, lat in coords).encode()).hexdigest()[:16]
