"""The road network every source snaps to: OSM drive-graph edges, segment_id = "u-v-key".

Reads the GraphML that `python -m pull osm_drive_graph` saves (stdlib XML, no osmnx needed),
links each edge to a DataSF street (cnn) and its posted speed limit when those snapshots
exist, and picks a fallback free-flow speed per AGENTS.md "Traffic data normalization".
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from pull.check import FREEWAY_SENTINEL, cnn_key

from .geo import (LineIndex, LonLat, bearing_deg, dedupe_coords, haversine_m, line_length_m, line_midpoint,
                  lines_of, midpoint)

_NS = "{http://graphml.graphdrawing.org/xmlns}"
_WKT_LINE = re.compile(r"LINESTRING\s*\((.*)\)", re.I | re.S)

UNPOSTED_MPH = 25.0  # California default on unposted city streets
# Only used when an edge has neither a DataSF limit nor an OSM maxspeed.
HIGHWAY_DEFAULT_MPH = {"motorway": 55.0, "motorway_link": 35.0, "trunk": 40.0, "trunk_link": 30.0}

CNN_MATCH_M = 15.0     # edge midpoint -> nearest DataSF street line
SNAP_M = 20.0          # provider piece midpoint -> nearest edge
SNAP_MAX_ANGLE = 45.0  # piece must run the same way as the edge


@dataclass
class Edge:
    segment_id: str
    u: str
    v: str
    key: str
    coords: list[LonLat]
    length_m: float
    name: str | None = None
    highway: str | None = None
    oneway: bool | None = None
    lanes: str | None = None
    maxspeed_mph: float | None = None
    osmid: Any = None
    cnn: str | None = None
    speed_limit_mph: float | None = None

    @property
    def free_flow_mph(self) -> float:
        """Fallback free flow: DataSF posted limit, else OSM maxspeed, else a road-class default."""
        if self.speed_limit_mph:
            return self.speed_limit_mph
        if self.maxspeed_mph:
            return self.maxspeed_mph
        return HIGHWAY_DEFAULT_MPH.get(self.highway or "", UNPOSTED_MPH)


def _first(v: str | None) -> str | None:
    """OSMnx writes list attributes as "['a', 'b']"; keep the first value."""
    if v is None:
        return None
    if v.startswith("[") and v.endswith("]"):
        parts = [p.strip().strip("'\"") for p in v[1:-1].split(",") if p.strip()]
        return parts[0] if parts else None
    return v


def maxspeed_mph(raw: str | None) -> float | None:
    """'25 mph' / "['25 mph', '30 mph']" / '40' (km/h, OSM default unit) -> lowest mph."""
    if not raw:
        return None
    vals = []
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(mph)?", raw):
        n = float(m.group(1))
        vals.append(n if m.group(2) else round(n / 1.609344, 1))
    return min(vals) if vals else None


def _wkt_coords(wkt: str) -> list[LonLat] | None:
    m = _WKT_LINE.match(wkt.strip())
    if not m:
        return None
    return dedupe_coords(pair.split()[:2] for pair in m.group(1).split(","))


def read_graphml(path: Path) -> dict[str, Edge]:
    keys: dict[str, str] = {}
    nodes: dict[str, LonLat] = {}
    edges: dict[str, Edge] = {}
    for _, el in ET.iterparse(path, events=("end",)):
        tag = el.tag.replace(_NS, "")
        if tag == "key":
            keys[el.get("id")] = f"{el.get('for')}:{el.get('attr.name')}"
        elif tag == "node":
            d = {keys.get(x.get("key"), ""): x.text for x in el.findall(f"{_NS}data")}
            try:
                nodes[el.get("id")] = (float(d["node:x"]), float(d["node:y"]))
            except (KeyError, TypeError, ValueError):
                pass
            el.clear()
        elif tag == "edge":
            d = {keys.get(x.get("key"), ""): x.text for x in el.findall(f"{_NS}data")}
            u, v = el.get("source"), el.get("target")
            k = d.get("edge:key") or el.get("id") or "0"
            coords = _wkt_coords(d["edge:geometry"]) if d.get("edge:geometry") else None
            if not coords and u in nodes and v in nodes:
                coords = dedupe_coords([nodes[u], nodes[v]])
            if coords and len(coords) >= 2:
                sid = f"{u}-{v}-{k}"
                length = float(d["edge:length"]) if d.get("edge:length") else line_length_m(coords)
                edges[sid] = Edge(
                    segment_id=sid, u=u, v=v, key=k, coords=coords, length_m=length,
                    name=_first(d.get("edge:name")), highway=_first(d.get("edge:highway")),
                    oneway=(d.get("edge:oneway") or "").lower() == "true" if d.get("edge:oneway") else None,
                    lanes=_first(d.get("edge:lanes")), maxspeed_mph=maxspeed_mph(d.get("edge:maxspeed")),
                    osmid=d.get("edge:osmid"),
                )
            el.clear()
    return edges


@dataclass
class Network:
    edges: dict[str, Edge]
    index: LineIndex = field(default_factory=LineIndex)

    def __post_init__(self) -> None:
        for sid, e in self.edges.items():
            self.index.add(sid, e.coords)

    @classmethod
    def load(cls, graphml: Path, streets: Path | None = None, speed_limits: Path | None = None) -> "Network":
        net = cls(read_graphml(graphml))
        if streets and streets.exists():
            net.link_cnn(_snapshot_records(streets), _snapshot_records(speed_limits) if speed_limits and speed_limits.exists() else [])
        return net

    def link_cnn(self, street_rows: list[dict], limit_rows: list[dict]) -> int:
        """edge -> nearest DataSF street (cnn) by midpoint, then that cnn's posted limit."""
        streets = LineIndex()
        for row in street_rows:
            cnn = cnn_key(row.get("cnn"))
            for line in lines_of(row.get("line")):
                if cnn and len(line) >= 2:
                    streets.add(cnn, line)
        posted: dict[str, float] = {}
        for row in limit_rows:
            cnn = cnn_key(row.get("cnn"))
            try:
                mph = int(float(row.get("speedlimit")))
            except (TypeError, ValueError):
                continue
            if cnn and 0 < mph < FREEWAY_SENTINEL:  # 0 = unposted, 99 = state freeway (not a limit)
                posted[cnn] = min(mph, posted.get(cnn, mph))
        linked = 0
        for e in self.edges.values():
            mid = line_midpoint(e.coords)
            hits = streets.near(mid, CNN_MATCH_M) if mid else []
            e.cnn = hits[0][1] if hits else None
            e.speed_limit_mph = posted.get(e.cnn) if e.cnn else None
            linked += e.cnn is not None
        return linked

    def snap_piece(self, a: LonLat, b: LonLat, radius_m: float = SNAP_M) -> str | None:
        """segment_id for the piece a->b: nearest edge to its midpoint running the same way.
        Two-way streets have overlapping u-v and v-u edges; the heading picks the right one."""
        if a == b:
            return None
        return self.index.nearest_heading(midpoint(a, b), bearing_deg(a, b), radius_m, SNAP_MAX_ANGLE)

    def snap_line(self, coords: Sequence[LonLat]) -> list[tuple[str, float]]:
        """Ordered [(segment_id, metres of the line on it)] for a provider line, detours pruned."""
        out: list[tuple[str, float]] = []
        for a, b in zip(coords, coords[1:]):
            sid = self.snap_piece(a, b)
            if sid is None:
                continue
            d = haversine_m(a, b)
            if out and out[-1][0] == sid:
                out[-1] = (sid, out[-1][1] + d)
            else:
                out.append((sid, d))
        keep = set(self.prune_detours([sid for sid, _ in out]))
        return [(sid, d) for sid, d in out if sid in keep]

    def prune_detours(self, seq: Sequence[str]) -> list[str]:
        """Drop matches that break an otherwise connected path.

        Snapping pieces one by one lets a noisy piece near an intersection land on a short cross
        street or the opposite direction. If the neighbours on both sides connect to each other
        (prev.v == next.u) and the middle match doesn't link them, it's a detour the route never
        drove. Consecutive duplicates are collapsed first; ends are left alone (a missed edge in
        the middle would otherwise make a real end look disconnected)."""
        path = [s for i, s in enumerate(seq) if i == 0 or s != seq[i - 1]]
        changed = True
        while changed and len(path) >= 3:
            changed = False
            for i in range(1, len(path) - 1):
                p, s, n = (self.edges[x] for x in path[i - 1:i + 2])
                if p.v == n.u and not (p.v == s.u and s.v == n.u):
                    del path[i]
                    changed = True
                    break
        return path


def _snapshot_records(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8")).get("records", [])


def road_segment_doc(e: Edge) -> dict:
    """Mongo road_segments document (AGENTS.md: segment_id unique, cnn, geometry 2dsphere)."""
    return {
        "segment_id": e.segment_id, "u": e.u, "v": e.v, "key": e.key, "osmid": e.osmid,
        "name": e.name, "highway": e.highway, "oneway": e.oneway, "lanes": e.lanes,
        "length_m": round(e.length_m, 2), "maxspeed_mph": e.maxspeed_mph,
        "cnn": e.cnn, "speed_limit_mph": e.speed_limit_mph, "free_flow_speed_mph": e.free_flow_mph,
        "geometry": {"type": "LineString", "coordinates": [list(c) for c in e.coords]},
    }
