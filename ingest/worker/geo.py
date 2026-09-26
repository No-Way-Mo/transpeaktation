"""Small stdlib geometry helpers. Coordinates are (lon, lat) everywhere."""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Iterable, Sequence

LonLat = tuple[float, float]

EARTH_R_M = 6_371_008.8
# Metres per degree near San Francisco (37.77 N); good to <0.5% across the city.
M_PER_DEG_LAT = 111_132.0
M_PER_DEG_LON = 111_320.0 * math.cos(math.radians(37.77))


def haversine_m(a: LonLat, b: LonLat) -> float:
    p1, p2 = math.radians(a[1]), math.radians(b[1])
    dp, dl = p2 - p1, math.radians(b[0] - a[0])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R_M * math.asin(math.sqrt(h))


def line_length_m(coords: Sequence[LonLat]) -> float:
    return sum(haversine_m(a, b) for a, b in zip(coords, coords[1:]))


def bearing_deg(a: LonLat, b: LonLat) -> float:
    """Heading from a to b, degrees clockwise from north (planar, fine at city scale)."""
    dx = (b[0] - a[0]) * M_PER_DEG_LON
    dy = (b[1] - a[1]) * M_PER_DEG_LAT
    return math.degrees(math.atan2(dx, dy)) % 360


def angle_diff(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return min(d, 360 - d)


def point_segment_m(p: LonLat, a: LonLat, b: LonLat) -> float:
    """Distance from p to segment a-b in metres (local planar projection)."""
    px, py = p[0] * M_PER_DEG_LON, p[1] * M_PER_DEG_LAT
    ax, ay = a[0] * M_PER_DEG_LON, a[1] * M_PER_DEG_LAT
    bx, by = b[0] * M_PER_DEG_LON, b[1] * M_PER_DEG_LAT
    dx, dy = bx - ax, by - ay
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def midpoint(a: LonLat, b: LonLat) -> LonLat:
    return (a[0] + b[0]) / 2, (a[1] + b[1]) / 2


def line_midpoint(coords: Sequence[LonLat]) -> LonLat | None:
    """Point halfway along a line by length."""
    if not coords:
        return None
    half = line_length_m(coords) / 2
    walked = 0.0
    for a, b in zip(coords, coords[1:]):
        d = haversine_m(a, b)
        if d and walked + d >= half:
            t = (half - walked) / d
            return a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
        walked += d
    return coords[0]


def dedupe_coords(coords: Iterable[Sequence[float]]) -> list[LonLat]:
    out: list[LonLat] = []
    for c in coords:
        p = (round(float(c[0]), 7), round(float(c[1]), 7))
        if not out or out[-1] != p:
            out.append(p)
    return out


def lines_of(geom: dict | None) -> list[list[LonLat]]:
    """LineString / MultiLineString -> list of lines; anything else -> []."""
    if not geom:
        return []
    if geom.get("type") == "LineString":
        return [dedupe_coords(geom["coordinates"])]
    if geom.get("type") == "MultiLineString":
        return [dedupe_coords(line) for line in geom["coordinates"]]
    return []


class LineIndex:
    """Grid index over line pieces. Each piece keeps its owner id and heading, so a query
    can ask for the nearest piece that also runs in a given direction."""

    CELL_DEG = 0.0005  # ~55 m north-south, ~44 m east-west

    def __init__(self) -> None:
        self._cells: dict[tuple[int, int], list[tuple[str, LonLat, LonLat, float]]] = defaultdict(list)

    def _cell(self, lon: float, lat: float) -> tuple[int, int]:
        return int(math.floor(lon / self.CELL_DEG)), int(math.floor(lat / self.CELL_DEG))

    def add(self, owner: str, coords: Sequence[LonLat]) -> None:
        for a, b in zip(coords, coords[1:]):
            if a == b:
                continue
            piece = (owner, a, b, bearing_deg(a, b))
            (x0, y0), (x1, y1) = self._cell(min(a[0], b[0]), min(a[1], b[1])), self._cell(max(a[0], b[0]), max(a[1], b[1]))
            for x in range(x0, x1 + 1):
                for y in range(y0, y1 + 1):
                    self._cells[(x, y)].append(piece)

    def _hits(self, p: LonLat, radius_m: float) -> list[tuple[float, str, float]]:
        """Every piece within radius as (distance_m, owner, heading), nearest first. Keeps all
        pieces: a two-way street's u-v and v-u edges overlap exactly and differ only by heading."""
        reach = int(math.ceil(radius_m / (self.CELL_DEG * M_PER_DEG_LON)))
        cx, cy = self._cell(*p)
        seen: set[int] = set()
        hits = []
        for x in range(cx - reach, cx + reach + 1):
            for y in range(cy - reach, cy + reach + 1):
                for piece in self._cells.get((x, y), ()):
                    if id(piece) not in seen:
                        seen.add(id(piece))
                        d = point_segment_m(p, piece[1], piece[2])
                        if d <= radius_m:
                            hits.append((d, piece[0], piece[3]))
        hits.sort()
        return hits

    def near(self, p: LonLat, radius_m: float) -> list[tuple[float, str, float]]:
        """[(distance_m, owner, heading)] within radius, nearest first, one entry per owner."""
        out, seen = [], set()
        for hit in self._hits(p, radius_m):
            if hit[1] not in seen:
                seen.add(hit[1])
                out.append(hit)
        return out

    def nearest_heading(self, p: LonLat, heading: float, radius_m: float, max_angle: float) -> str | None:
        """Nearest owner whose piece near p runs within max_angle of heading."""
        return next((o for _, o, h in self._hits(p, radius_m) if angle_diff(heading, h) <= max_angle), None)
