"""Joins between road networks, by location (deterministic, no external calls):

- OSM edge -> DataSF cnn: the street segment nearest the edge's midpoint, within CNN_MATCH_M
  (fills road_segments.cnn; the TODO.md "link cnn to OSM" step).
- closure / incident -> road_segment_ids: OSM edges the location lies on (road_incidents
  contract). Points take every edge within POINT_M of the nearest one (an intersection
  touches all its approaches); lines take edges whose midpoint lies on the line.
- cnn -> DataSF speed limit, embedded in road_segments as `speed_limit` (source meaning only).
"""
from __future__ import annotations

from typing import Iterable

from .geo import LineIndex, StreetIndex, _lines, _seg_dist_m, haversine_m, line_midpoint
from .records import Record

CNN_MATCH_M = 15.0
POINT_M = 25.0
POINT_TIE_M = 5.0
LINE_SAMPLE_M = 20.0
LINE_M = 15.0
MAX_SEGMENT_IDS = 200


def match_cnn(edge_geom: dict | None, streets: StreetIndex) -> tuple[str, float] | None:
    mid = line_midpoint(edge_geom)
    return streets.nearest_segment(mid, CNN_MATCH_M) if mid else None


def _samples(line: list[tuple[float, float]]) -> Iterable[tuple[float, float]]:
    for a, b in zip(line, line[1:]):
        steps = max(1, int(haversine_m(a, b) // LINE_SAMPLE_M))
        for i in range(steps):
            t = i / steps
            yield a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
    if line:
        yield line[-1]


def _dist_to_lines(p: tuple[float, float], lines: list[list[tuple[float, float]]]) -> float:
    return min((_seg_dist_m(p, a, b) for line in lines for a, b in zip(line, line[1:])), default=float("inf"))


def segment_ids_for(geom: dict | None, osm: LineIndex) -> list[str]:
    if not geom:
        return []
    if geom["type"] in ("Point", "MultiPoint"):
        pts = [geom["coordinates"]] if geom["type"] == "Point" else geom["coordinates"]
        ids: set[str] = set()
        for p in pts:
            hits = osm.near(tuple(p), POINT_M)
            if hits:
                ids.update(k for d, k, _ in hits if d <= hits[0][0] + POINT_TIE_M)
        return sorted(ids)[:MAX_SEGMENT_IDS]
    lines = _lines(geom)
    if not lines:  # polygons: use the outer ring as a line
        if geom["type"] == "Polygon":
            lines = [[tuple(p) for p in geom["coordinates"][0]]]
        elif geom["type"] == "MultiPolygon":
            lines = [[tuple(p) for p in poly[0]] for poly in geom["coordinates"]]
    candidates: set[str] = set()
    for line in lines:
        for p in _samples(line):
            candidates.update(k for _, k, _ in osm.near(p, LINE_M))
    keep = [k for k in candidates if (m := line_midpoint(osm.geometry[k])) and _dist_to_lines(m, lines) <= LINE_M]
    return sorted(keep)[:MAX_SEGMENT_IDS]


def speed_limits_by_cnn(records: Iterable[Record]) -> dict[str, dict]:
    """cnn -> speed limit (lowest objectid wins when a cnn has several rows; count kept)."""
    by_cnn: dict[str, list[Record]] = {}
    for r in records:
        if r.source == "speed_limits" and r.road_ref and r.road_ref.get("cnn"):
            by_cnn.setdefault(r.road_ref["cnn"], []).append(r)
    out = {}
    for cnn, rs in by_cnn.items():
        rs.sort(key=lambda r: (len(r.source_id), r.source_id))
        a = rs[0].attributes
        out[cnn] = {"status": a["status"], "posted_mph": a["posted_mph"], "raw_value": a["raw_value"],
                    "source": "speed_limits", "source_id": rs[0].source_id, "rows": len(rs)}
    return out
