"""Edge geometry from the OSMnx GraphML that `python -m pull osm_drive_graph` saves next
to the snapshot (the JSON snapshot carries attributes only). Stdlib XML, streamed."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from .geo import GeometryError, LineIndex, normalize_geometry

_NS = "{http://graphml.graphdrawing.org/xmlns}"
_WKT_LINE = re.compile(r"LINESTRING\s*\((.*)\)", re.I | re.S)


def _wkt_line(wkt: str) -> list[list[float]] | None:
    m = _WKT_LINE.match(wkt.strip())
    if not m:
        return None
    return [[float(x) for x in pair.split()[:2]] for pair in m.group(1).split(",")]


def edge_geometries(path: Path) -> dict[str, dict]:
    """segment_id ("u-v-key", as Mongo road_segments.segment_id) -> LineString. Edges without a stored geometry get a straight u->v line."""
    keys: dict[str, str] = {}  # GraphML <key id> -> attribute name, per domain
    nodes: dict[str, list[float]] = {}
    edges: dict[str, dict] = {}
    for _, el in ET.iterparse(path, events=("end",)):
        tag = el.tag.replace(_NS, "")
        if tag == "key":
            keys[el.get("id")] = f"{el.get('for')}:{el.get('attr.name')}"
        elif tag == "node":
            data = {keys.get(d.get("key"), ""): d.text for d in el.findall(f"{_NS}data")}
            try:
                nodes[el.get("id")] = [float(data["node:x"]), float(data["node:y"])]
            except (KeyError, TypeError, ValueError):
                pass
            el.clear()
        elif tag == "edge":
            data = {keys.get(d.get("key"), ""): d.text for d in el.findall(f"{_NS}data")}
            u, v = el.get("source"), el.get("target")
            k = data.get("edge:key") or el.get("id") or "0"
            coords = _wkt_line(data["edge:geometry"]) if data.get("edge:geometry") else None
            if coords is None and u in nodes and v in nodes:
                coords = [nodes[u], nodes[v]]
            if coords:
                try:
                    edges[f"{u}-{v}-{k}"] = normalize_geometry({"type": "LineString", "coordinates": coords})
                except GeometryError:
                    pass
            el.clear()
    return edges


def edge_index(path: Path) -> LineIndex:
    idx = LineIndex()
    for segment_id, geom in sorted(edge_geometries(path).items()):
        idx.add(segment_id, geom)
    return idx
