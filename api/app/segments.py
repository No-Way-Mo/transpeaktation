"""Match a route's geometry to OSM drive-graph edges. IDs are "u-v-key", the same segment_id used by
Mongo road_segments and Tiger traffic_metrics / prediction_metrics (see AGENTS.md → Data stores)."""
from __future__ import annotations

from pathlib import Path

import osmnx as ox
from shapely.geometry import MultiPoint

GRAPH_FILE = Path(__file__).resolve().parent.parent / "data" / "sf_drive.graphml"


class Segments:
    def __init__(self) -> None:
        self.graph = None  # projected (metres) so nearest-edge distances are real distances
        self.error: str | None = None

    @property
    def status(self) -> str:
        return "ready" if self.graph is not None else (f"failed: {self.error}" if self.error else "loading")

    def load(self, path: Path = GRAPH_FILE) -> None:
        """First run downloads SF from OpenStreetMap (~15 s) and caches it; later runs read the cache."""
        try:
            if path.exists():
                g = ox.load_graphml(path)
            else:
                g = ox.graph_from_place("San Francisco, California, USA", network_type="drive")
                path.parent.mkdir(parents=True, exist_ok=True)
                ox.save_graphml(g, path)
            self.use(g)
        except Exception as e:  # keep serving routes without segment IDs rather than crash the API
            self.error = f"{type(e).__name__}: {e}"

    def use(self, g) -> None:
        self.graph = ox.project_graph(g)

    def lengths(self, segment_ids: list[str]) -> dict[str, float]:
        """segment_id -> edge length in metres (unknown IDs are left out)."""
        g, out = self.graph, {}
        if g is None:
            return out
        for sid in segment_ids:
            try:
                u, v, k = (int(x) for x in sid.split("-"))
                out[sid] = float(g.edges[u, v, k]["length"])
            except (ValueError, KeyError):
                continue
        return out

    def names(self, segment_ids: list[str]) -> dict[str, str]:
        """segment_id -> OSM street name (the first, for edges merged from several; unnamed edges are left out)."""
        g, out = self.graph, {}
        if g is None:
            return out
        for sid in segment_ids:
            try:
                u, v, k = (int(x) for x in sid.split("-"))
                name = g.edges[u, v, k].get("name")
            except (ValueError, KeyError):
                continue
            name = name[0] if isinstance(name, list) and name else name
            if isinstance(name, str) and name.startswith("["):  # graphml can keep lists as "['A', 'B']"
                name = name.strip("[]").split(",")[0].strip(" '\"")
            if isinstance(name, str) and name:
                out[sid] = name
        return out

    def route_geometry(self, coords: list[list[float]], segment_ids: list[str]) -> tuple[list, list] | None:
        """For turn-by-turn on a route given as segments + line (app/directions.py): the line's points in the graph's
        metres, and the node where each segment meets the next. None without a graph or for an unknown segment."""
        g = self.graph
        if g is None or len(coords) < 2:
            return None
        try:
            joints = [(g.nodes[int(s.split("-")[0])]["x"], g.nodes[int(s.split("-")[0])]["y"]) for s in segment_ids[1:]]
        except (ValueError, KeyError, IndexError):
            return None
        pts, _ = ox.projection.project_geometry(MultiPoint([(lon, lat) for lat, lon in coords]), to_crs=g.graph["crs"])
        return [(q.x, q.y) for q in pts.geoms], joints

    def match(self, coords: list[list[float]]) -> list[str] | None:
        """coords: [[lat, lon], ...] along the route. Returns edge IDs in driving order, or None if no graph."""
        g = self.graph
        if g is None or len(coords) < 2:
            return None
        pts, _ = ox.projection.project_geometry(MultiPoint([(lon, lat) for lat, lon in coords]), to_crs=g.graph["crs"])
        xy = [(p.x, p.y) for p in pts.geoms]
        pieces = [(a, b) for a, b in zip(xy, xy[1:]) if a != b]
        if not pieces:
            return None
        # ponytail: nearest edge per polyline piece, no HMM map matching. Good on city grids; can slip onto a
        # parallel ramp/frontage road. Upgrade: Mapbox Map Matching or Valhalla trace_attributes.
        mids = [((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) for a, b in pieces]
        edges = ox.distance.nearest_edges(g, [m[0] for m in mids], [m[1] for m in mids])
        out: list[str] = []
        for (u, v, k), (a, b) in zip(edges, pieces):
            # Two-way streets are two directed edges with the same geometry; keep the one we drive along.
            nu, nv = g.nodes[u], g.nodes[v]
            if (nv["x"] - nu["x"]) * (b[0] - a[0]) + (nv["y"] - nu["y"]) * (b[1] - a[1]) < 0 and g.has_edge(v, u):
                u, v, k = v, u, min(g[v][u])
            sid = f"{u}-{v}-{k}"
            if not out or out[-1] != sid:
                out.append(sid)
        return out
