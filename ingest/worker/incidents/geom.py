"""Geometry normalization (WGS84 GeoJSON, [lon, lat]) and the SF street-network index.

The street index answers the two `cnn` questions from the quality checks:
- is this cnn a street segment or an intersection (node)?
- what geometry does a geometry-less, cnn-only record have?
and snaps cnn-less point records to the nearest segment.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Iterable, Iterator

from pull.check import BAY_BBOX, cnn_key  # noqa: F401  (BAY_BBOX re-exported for adapters)
from pull.feeds import SF_BBOX  # noqa: F401

Coord = tuple[float, float]
PRECISION = 7  # ~1 cm; keeps output deterministic
_DEPTH = {"Point": 0, "MultiPoint": 1, "LineString": 1, "MultiLineString": 2, "Polygon": 2, "MultiPolygon": 3}


class GeometryError(ValueError):
    pass


def valid_lonlat(lon: Any, lat: Any) -> bool:
    try:
        lon, lat = float(lon), float(lat)
    except (TypeError, ValueError):
        return False
    if not (math.isfinite(lon) and math.isfinite(lat)):
        return False
    if lon == 0 and lat == 0:  # "null island" is always a placeholder
        return False
    return -180 <= lon <= 180 and -90 <= lat <= 90


def _pos(p: Any) -> list[float]:
    if not isinstance(p, (list, tuple)) or len(p) < 2:
        raise GeometryError(f"bad position {p!r}")
    if not valid_lonlat(p[0], p[1]):
        raise GeometryError(f"invalid coordinate {p[:2]!r}")
    return [round(float(p[0]), PRECISION), round(float(p[1]), PRECISION)]  # drops z/m


def _coords(c: Any, depth: int, gtype: str) -> list:
    if depth == 0:
        return _pos(c)
    if not isinstance(c, list) or not c:
        raise GeometryError(f"empty or malformed {gtype} coordinates")
    out = [_coords(x, depth - 1, gtype) for x in c]
    if depth == 1 and gtype in ("LineString", "MultiLineString") and len(out) < 2:
        raise GeometryError(f"{gtype} part needs at least 2 positions")
    if depth == 1 and gtype in ("Polygon", "MultiPolygon") and (len(out) < 4 or out[0] != out[-1]):
        raise GeometryError(f"{gtype} ring must be closed with at least 4 positions")
    return out


def point(lon: Any, lat: Any) -> dict:
    return {"type": "Point", "coordinates": _pos([lon, lat])}


def normalize_geometry(value: Any) -> dict | None:
    """GeoJSON geometry or Socrata location dict -> clean GeoJSON; None when absent.
    Raises GeometryError when a location is present but malformed."""
    if value in (None, "", {}):
        return None
    if not isinstance(value, dict):
        raise GeometryError(f"unsupported geometry value {type(value).__name__}")
    if "coordinates" in value:
        gtype = value.get("type")
        if gtype not in _DEPTH:
            raise GeometryError(f"unsupported geometry type {gtype!r}")
        if value["coordinates"] in (None, []):
            return None
        return {"type": gtype, "coordinates": _coords(value["coordinates"], _DEPTH[gtype], gtype)}
    if "latitude" in value or "longitude" in value:
        lat, lon = value.get("latitude"), value.get("longitude")
        if lat in (None, "") and lon in (None, ""):
            return None
        return point(lon, lat)
    raise GeometryError(f"unrecognized geometry keys {sorted(value)[:5]}")


def iter_coords(geom: dict | None) -> Iterator[Coord]:
    def walk(c):
        if c and isinstance(c[0], (int, float)):
            yield float(c[0]), float(c[1])
        else:
            for part in c:
                yield from walk(part)
    if geom:
        yield from walk(geom["coordinates"])


def representative_point(geom: dict | None) -> Coord | None:
    pts = list(iter_coords(geom))
    if not pts:
        return None
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def inside(geom: dict | None, bbox: tuple[float, float, float, float]) -> bool:
    """True when every coordinate is inside bbox (lon_min, lat_min, lon_max, lat_max)."""
    pts = list(iter_coords(geom))
    return bool(pts) and all(bbox[0] <= x <= bbox[2] and bbox[1] <= y <= bbox[3] for x, y in pts)


def haversine_m(a: Coord, b: Coord) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6_371_008.8 * math.asin(math.sqrt(h))


def min_distance_m(g1: dict | None, g2: dict | None, max_vertices: int = 400) -> float | None:
    """Smallest vertex-to-vertex distance (good enough for 100 m dedupe radii)."""
    a, b = list(iter_coords(g1))[:max_vertices], list(iter_coords(g2))[:max_vertices]
    if not a or not b:
        return None
    return min(haversine_m(p, q) for p in a for q in b)


def _seg_dist_m(p: Coord, a: Coord, b: Coord) -> float:
    """Point-to-segment distance in a local equirectangular projection (fine at city scale)."""
    kx = 111_320 * math.cos(math.radians(p[1]))
    ky = 110_540
    px, py = 0.0, 0.0
    ax, ay = (a[0] - p[0]) * kx, (a[1] - p[1]) * ky
    bx, by = (b[0] - p[0]) * kx, (b[1] - p[1]) * ky
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
    return math.hypot(ax + t * dx, ay + t * dy)


def _lines(geom: dict | None) -> list[list[Coord]]:
    if not geom:
        return []
    t, c = geom["type"], geom["coordinates"]
    if t == "LineString":
        return [[tuple(p) for p in c]]
    if t == "MultiLineString":
        return [[tuple(p) for p in part] for part in c]
    return []


def line_length_m(geom: dict | None) -> float:
    return sum(haversine_m(a, b) for line in _lines(geom) for a, b in zip(line, line[1:]))


def line_midpoint(geom: dict | None) -> Coord | None:
    """Point halfway along a (Multi)LineString; the point itself for a Point."""
    if geom and geom["type"] == "Point":
        return tuple(geom["coordinates"])
    pieces = [(a, b, haversine_m(a, b)) for line in _lines(geom) for a, b in zip(line, line[1:])]
    total = sum(d for _, _, d in pieces)
    if not pieces:
        return None
    half = total / 2
    for a, b, d in pieces:
        if half <= d and d > 0:
            t = half / d
            return a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
        half -= d
    return pieces[-1][1]


def bearing_deg(a: Coord, b: Coord) -> float:
    """Initial compass bearing a -> b (0 = north, 90 = east)."""
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    y = math.sin(lon2 - lon1) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1)
    return math.degrees(math.atan2(y, x)) % 360


def angle_diff(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


class LineIndex:
    """Grid index over line pieces, keyed by an id (DataSF cnn or OSM segment_id)."""

    CELL = 0.001  # degrees (~90-110 m)

    def __init__(self) -> None:
        self.geometry: dict[str, dict] = {}
        self._grid: dict[tuple[int, int], list[tuple[str, Coord, Coord]]] = defaultdict(list)

    def add(self, key: str, geom: dict | None) -> None:
        self.geometry[key] = geom
        for line in _lines(geom):
            for a, b in zip(line, line[1:]):
                for cell in self._cells(a, b):
                    self._grid[cell].append((key, a, b))

    def __len__(self) -> int:
        return len(self.geometry)

    def _cell(self, p: Coord) -> tuple[int, int]:
        return int(math.floor(p[0] / self.CELL)), int(math.floor(p[1] / self.CELL))

    def _cells(self, a: Coord, b: Coord) -> Iterator[tuple[int, int]]:
        (x0, y0), (x1, y1) = self._cell(a), self._cell(b)
        for x in range(min(x0, x1), max(x0, x1) + 1):
            for y in range(min(y0, y1), max(y0, y1) + 1):
                yield x, y

    def near(self, p: Coord, max_m: float) -> list[tuple[float, str, float]]:
        """[(distance_m, key, bearing of the closest piece)] within max_m, nearest first, one per key."""
        cx, cy = self._cell(p)
        reach = int(math.ceil(max_m / 80)) + 1
        best: dict[str, tuple[float, float]] = {}
        for x in range(cx - reach, cx + reach + 1):
            for y in range(cy - reach, cy + reach + 1):
                for key, a, b in self._grid.get((x, y), ()):
                    d = _seg_dist_m(p, a, b)
                    if d <= max_m and (key not in best or d < best[key][0]):
                        best[key] = (d, bearing_deg(a, b))
        return sorted((round(d, 1), k, brg) for k, (d, brg) in best.items())

    def nearest(self, p: Coord, max_m: float) -> tuple[str, float] | None:
        hits = self.near(p, max_m)
        return (hits[0][1], hits[0][0]) if hits else None


class StreetIndex:
    """SF street network (DataSF `streets`, keyed by cnn) for cnn lookups and snapping."""

    def __init__(self) -> None:
        self.lines = LineIndex()
        self.nodes: dict[str, Coord | None] = {}  # intersection cnn -> point

    @property
    def segments(self) -> dict[str, dict]:
        return self.lines.geometry

    @classmethod
    def from_rows(cls, rows: Iterable[dict], geo_field: str = "line") -> "StreetIndex":
        idx = cls()
        for r in rows:
            cnn = cnn_key(r.get("cnn"))
            if not cnn:
                continue
            try:
                geom = normalize_geometry(r.get(geo_field))
            except GeometryError:
                geom = None
            idx.lines.add(cnn, geom)
            lines = _lines(geom)
            ends = (lines[0][0], lines[-1][-1]) if lines else (None, None)
            for key, pt in zip((r.get("f_node_cnn"), r.get("t_node_cnn")), ends):
                node = cnn_key(key)
                if node and idx.nodes.get(node) is None:
                    idx.nodes[node] = pt
        return idx

    def __len__(self) -> int:
        return len(self.lines)

    def classify(self, cnn: Any) -> str:
        """'segment' | 'intersection' | 'unknown' (a cnn names either; see TODO.md)."""
        key = cnn_key(cnn)
        if key in self.segments:
            return "segment"
        if key in self.nodes:
            return "intersection"
        return "unknown"

    def geometry_for(self, cnn: Any) -> dict | None:
        key = cnn_key(cnn)
        if key in self.segments:
            return self.segments[key]
        pt = self.nodes.get(key)
        return {"type": "Point", "coordinates": list(pt)} if pt else None

    def nearest_segment(self, p: Coord, max_m: float = 25.0) -> tuple[str, float] | None:
        return self.lines.nearest(p, max_m)
