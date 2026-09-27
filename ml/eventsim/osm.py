"""Read the OSMnx GraphML snapshot that `ingest` saves. segment_id = "u-v-key" (AGENTS.md)."""
from __future__ import annotations

import ast
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .config import HIGHWAY_DEFAULT_MPH

_NS = "{http://graphml.graphdrawing.org/xmlns}"
_WKT = re.compile(r"LINESTRING\s*\((.*)\)", re.I | re.S)

# Road-class rank: used for SUMO priority and as a model feature.
HIGHWAY_RANK = {"motorway": 7, "trunk": 6, "primary": 5, "secondary": 4, "tertiary": 3,
                "motorway_link": 4, "trunk_link": 4, "primary_link": 3, "secondary_link": 3,
                "tertiary_link": 2, "unclassified": 2, "residential": 1, "living_street": 0}


def _lit(v: str | None):
    if v is None:
        return None
    s = v.strip()
    if s.startswith("["):
        try:
            return ast.literal_eval(s)
        except (ValueError, SyntaxError):
            return s
    return s


def _first_str(v) -> str | None:
    v = _lit(v) if isinstance(v, str) else v
    if isinstance(v, list):
        return str(v[0]) if v else None
    return v


def parse_mph(v) -> float | None:
    """OSM maxspeed ('25 mph', ['25 mph','30 mph'], '40') -> the highest posted mph, or None."""
    v = _lit(v) if isinstance(v, str) else v
    vals = v if isinstance(v, list) else [v]
    out = []
    for s in vals:
        if s is None:
            continue
        m = re.match(r"\s*(\d+(?:\.\d+)?)\s*(mph|km/h|kph)?", str(s))
        if m:
            x = float(m.group(1))
            out.append(x * 0.621371 if (m.group(2) or "").startswith("k") else x)
    return max(out) if out else None


def parse_lanes(v) -> int | None:
    v = _lit(v) if isinstance(v, str) else v
    vals = v if isinstance(v, list) else [v]
    out = []
    for s in vals:
        try:
            out.append(int(float(str(s).split(";")[0])))
        except (TypeError, ValueError):
            pass
    return max(out) if out else None


@dataclass
class Node:
    id: str
    lon: float
    lat: float
    highway: str | None = None
    street_count: int | None = None


@dataclass
class Edge:
    segment_id: str
    u: str
    v: str
    key: str
    coords: list[tuple[float, float]]
    length_m: float
    osmids: list[int] = field(default_factory=list)
    highway: str | None = None
    name: str | None = None
    lanes: int | None = None
    maxspeed_mph: float | None = None
    oneway: bool = False

    @property
    def rank(self) -> int:
        return HIGHWAY_RANK.get(self.highway or "", 1)


def load_graphml(path: Path) -> tuple[dict[str, Node], dict[str, Edge]]:
    root = ET.parse(path).getroot()
    keys = {k.get("id"): k.get("attr.name") for k in root.iter(f"{_NS}key")}
    graph = root.find(f"{_NS}graph")
    nodes: dict[str, Node] = {}
    edges: dict[str, Edge] = {}
    for n in graph.iter(f"{_NS}node"):
        d = {keys[x.get("key")]: x.text for x in n.findall(f"{_NS}data")}
        sc = d.get("street_count")
        nodes[n.get("id")] = Node(n.get("id"), float(d["x"]), float(d["y"]), d.get("highway"),
                                  int(float(sc)) if sc else None)
    for e in graph.iter(f"{_NS}edge"):
        d = {keys[x.get("key")]: x.text for x in e.findall(f"{_NS}data")}
        u, v, k = e.get("source"), e.get("target"), e.get("id") or "0"
        m = _WKT.match(d.get("geometry") or "")
        if m:
            coords = [tuple(map(float, p.split())) for p in m.group(1).split(",")]
        else:
            coords = [(nodes[u].lon, nodes[u].lat), (nodes[v].lon, nodes[v].lat)]
        osm = _lit(d.get("osmid"))
        osmids = [int(x) for x in (osm if isinstance(osm, list) else [osm]) if x is not None]
        sid = f"{u}-{v}-{k}"
        edges[sid] = Edge(
            segment_id=sid, u=u, v=v, key=k, coords=coords, length_m=float(d.get("length") or 0),
            osmids=osmids, highway=_first_str(d.get("highway")), name=_first_str(d.get("name")),
            lanes=parse_lanes(d.get("lanes")), maxspeed_mph=parse_mph(d.get("maxspeed")),
            oneway=str(d.get("oneway")).lower() == "true",
        )
    return nodes, edges


_SUFFIX = {"STREET": "ST", "AVENUE": "AVE", "BOULEVARD": "BLVD", "DRIVE": "DR", "ROAD": "RD", "PLACE": "PL",
           "TERRACE": "TER", "COURT": "CT", "LANE": "LN", "WAY": "WAY", "ALLEY": "ALY", "HIGHWAY": "HWY"}
_ORD = {"FIRST": "01ST", "SECOND": "02ND", "THIRD": "03RD", "FOURTH": "04TH", "FIFTH": "05TH", "SIXTH": "06TH",
        "SEVENTH": "07TH", "EIGHTH": "08TH", "NINTH": "09TH"}


def norm_street(name: str | None) -> str:
    """'17th Street' / '17TH ST' -> '17TH'; 'Market Street' -> 'MARKET' (street identity, suffix-free)."""
    if not name:
        return ""
    words = re.sub(r"[^A-Z0-9 ]", " ", name.upper()).split()
    if words and (words[-1] in _SUFFIX or words[-1] in _SUFFIX.values()):
        words = words[:-1]
    out = []
    for w in words:
        w = _ORD.get(w, w)
        m = re.fullmatch(r"(\d+)(ST|ND|RD|TH)", w)
        out.append(f"{int(m.group(1)):02d}{m.group(2)}" if m else w)
    return " ".join(out)


def fallback_free_flow_mph(e: Edge, posted: float | None) -> tuple[float, str]:
    """AGENTS.md fallback: posted limit, else OSM maxspeed, else class default / 25 mph. Not a measurement."""
    if posted:
        return posted, "datasf_posted"
    if e.maxspeed_mph:
        return e.maxspeed_mph, "osm_maxspeed"
    if e.highway in HIGHWAY_DEFAULT_MPH:
        return HIGHWAY_DEFAULT_MPH[e.highway], "class_default"
    return 25.0, "unposted_default"
