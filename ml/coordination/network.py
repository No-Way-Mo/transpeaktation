"""Versioned legal navigation graph: directed canonical roads (OSM u-v-key) and legal road-to-road connections.

Built from the same network artifacts the forecaster uses (`net_v3/arcs_c90.json`, `crosswalk.csv`, the batch's
`segments.parquet`, `prepared/patch.json` geometry). Connections come only from the SUMO network's lane connections
(turn prohibitions already applied); nothing is inferred from coordinates. Nothing is re-downloaded.

* `resource[i]` is the allocation resource of road i: its own index, or the representative road for a v3
  `merged_parallel` alias, so two aliases of one modelled carriageway never get two allocation budgets.
* Roads absorbed into merged junctions have no arcs of their own (SUMO arcs already join the roads on either side);
  they are unroutable and reported, never invented.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .config import Config

HIGHWAY_GROUPS = ["motorway", "trunk", "primary", "secondary", "tertiary", "residential", "minor"]
MPH_PER_MPS = 2.2369362920544
PIECE_M = 50.0          # long polyline pieces are split to this length for the snapping index
CELL_M = 100.0


def hw_group(h: str) -> str:
    h = str(h).replace("_link", "")
    return h if h in HIGHWAY_GROUPS else "minor"


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def network_version(net_dir: Path, name: str) -> tuple[str, dict]:
    """Same recipe as forecast/audit.py:network_version, so forecast exports and this graph can be matched."""
    files = ["network.json", "crosswalk.csv", "arcs_c90.json", "patch.con.xml", "net_c90.net.xml"]
    hashes = {f: sha256_file(net_dir / f) for f in files if (net_dir / f).exists()}
    v = f"{name}-{hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()[:12]}"
    return v, hashes


@dataclass(frozen=True)
class Snap:
    road: int               # directed road index
    fraction: float         # position along the road, 0 = start (u), 1 = end (v)
    distance_m: float       # from the query point
    lonlat: tuple           # snapped point


@dataclass
class RoadNetwork:
    ids: np.ndarray                  # [R] canonical road ids
    length_m: np.ndarray             # [R]
    free_flow_mph: np.ndarray        # [R]
    hw: np.ndarray                   # [R] road-class group
    lanes: np.ndarray                # [R] float, NaN = unknown
    lanes_assumed: np.ndarray        # [R] bool
    resource: np.ndarray             # [R] allocation resource index (self or representative)
    static_availability: np.ndarray  # [R] open | restricted | unavailable | alias
    gap: np.ndarray                  # [R] network gap label (none, merged_parallel, absorbed_junction, ...)
    src: np.ndarray                  # [A] legal arcs: road src can be followed by road dst (deduplicated)
    dst: np.ndarray
    geometry: list                   # [R] np.ndarray [n, 2] lon/lat, u -> v
    version: str
    proj: tuple                      # lon0, lat0 of the local metric projection
    stats: dict = field(default_factory=dict)

    def __post_init__(self):
        self.pos = {s: i for i, s in enumerate(self.ids)}
        order = np.lexsort((self.dst, self.src))
        self.src, self.dst = self.src[order], self.dst[order]
        ptr = np.zeros(self.n + 1, np.int64)
        np.add.at(ptr, self.src + 1, 1)
        self.succ_ptr = np.cumsum(ptr)
        self.indeg = np.bincount(self.dst, minlength=self.n)
        self.outdeg = np.bincount(self.src, minlength=self.n)
        self.ff_tt_s = self.length_m / np.maximum(self.free_flow_mph / MPH_PER_MPS, 0.1)
        self._build_snap_index()

    @property
    def n(self) -> int:
        return len(self.ids)

    def succ(self, i: int) -> np.ndarray:
        return self.dst[self.succ_ptr[i]:self.succ_ptr[i + 1]]

    def has_arc(self, a: int, b: int) -> bool:
        return bool(np.any(self.succ(a) == b))

    # ---- geometry -------------------------------------------------------------------------------------------------
    def to_xy(self, lonlat: np.ndarray) -> np.ndarray:
        lon0, lat0 = self.proj
        k = math.cos(math.radians(lat0))
        lonlat = np.asarray(lonlat, float).reshape(-1, 2)
        return np.stack([(lonlat[:, 0] - lon0) * 111_320.0 * k, (lonlat[:, 1] - lat0) * 110_540.0], 1)

    def _build_snap_index(self) -> None:
        ax, ay, bx, by, road, cum0 = [], [], [], [], [], []
        self.geom_xy = []
        self.geom_cum = []
        for i, g in enumerate(self.geometry):
            xy = self.to_xy(g)
            seg = np.hypot(*np.diff(xy, axis=0).T) if len(xy) > 1 else np.zeros(0)
            cum = np.concatenate([[0.0], np.cumsum(seg)])
            self.geom_xy.append(xy)
            self.geom_cum.append(cum)
            for s in range(len(seg)):
                parts = max(1, int(math.ceil(seg[s] / PIECE_M)))
                for p in range(parts):
                    t0, t1 = p / parts, (p + 1) / parts
                    a = xy[s] + (xy[s + 1] - xy[s]) * t0
                    b = xy[s] + (xy[s + 1] - xy[s]) * t1
                    ax.append(a[0]); ay.append(a[1]); bx.append(b[0]); by.append(b[1])
                    road.append(i); cum0.append(cum[s] + seg[s] * t0)
        self.pc_a = np.column_stack([ax, ay]) if ax else np.zeros((0, 2))
        self.pc_b = np.column_stack([bx, by]) if bx else np.zeros((0, 2))
        self.pc_road = np.asarray(road, np.int64)
        self.pc_cum0 = np.asarray(cum0, float)
        self.geom_len = np.array([c[-1] if len(c) else 0.0 for c in self.geom_cum])
        mid = (self.pc_a + self.pc_b) / 2
        cells = np.floor(mid / CELL_M).astype(np.int64)
        self._cells: dict[tuple, np.ndarray] = {}
        if len(cells):
            key = cells[:, 0] * 1_000_003 + cells[:, 1]
            order = np.argsort(key, kind="stable")
            ks, starts = np.unique(key[order], return_index=True)
            ends = np.append(starts[1:], len(order))
            for k, s, e in zip(ks, starts, ends):
                c = cells[order[s]]
                self._cells[(int(c[0]), int(c[1]))] = order[s:e]

    def snap(self, lonlat, allowed: np.ndarray | None = None, max_m: float = 75.0, tie_m: float = 3.0) -> list[Snap]:
        """Nearest allowed directed roads within max_m. Returns the best and any other road within tie_m of it (the
        opposite direction of a two-way street), nearest first. Empty = unsupported endpoint."""
        p = self.to_xy(np.asarray(lonlat, float))[0]
        c = np.floor(p / CELL_M).astype(np.int64)
        r = int(math.ceil((max_m + PIECE_M) / CELL_M))
        idx = [self._cells.get((int(c[0]) + dx, int(c[1]) + dy)) for dx in range(-r, r + 1) for dy in range(-r, r + 1)]
        idx = [x for x in idx if x is not None]
        if not idx:
            return []
        idx = np.concatenate(idx)
        if allowed is not None:
            idx = idx[allowed[self.pc_road[idx]]]
        if not len(idx):
            return []
        a, b = self.pc_a[idx], self.pc_b[idx]
        ab = b - a
        L2 = np.maximum((ab ** 2).sum(1), 1e-12)
        t = np.clip(((p - a) * ab).sum(1) / L2, 0, 1)
        q = a + ab * t[:, None]
        d = np.hypot(*(q - p).T)
        best: dict[int, tuple] = {}
        for j in np.argsort(d, kind="stable"):
            if d[j] > max_m:
                break
            rd = int(self.pc_road[idx[j]])
            if rd not in best:
                along = self.pc_cum0[idx[j]] + t[j] * math.sqrt(L2[j])
                frac = float(np.clip(along / self.geom_len[rd], 0, 1)) if self.geom_len[rd] > 0 else 0.0
                best[rd] = (float(d[j]), frac)
        if not best:
            return []
        dmin = min(v[0] for v in best.values())
        out = []
        for rd, (dist, frac) in sorted(best.items(), key=lambda kv: (kv[1][0], kv[0])):
            if dist <= dmin + tie_m:
                out.append(Snap(rd, frac, dist, tuple(self.point_at(rd, frac))))
        return out

    def point_at(self, i: int, frac: float) -> list:
        return self.subline(i, frac, frac)[0]

    def subline(self, i: int, f0: float, f1: float) -> list:
        """Polyline of road i between fractions f0 <= f1 (by length along the geometry), as [lon, lat] pairs."""
        g, cum = np.asarray(self.geometry[i], float), self.geom_cum[i]
        if len(g) < 2 or cum[-1] <= 0:
            return [list(map(float, g[0]))]
        L = cum[-1]

        def at(f):
            s = float(np.clip(f, 0, 1)) * L
            k = int(np.clip(np.searchsorted(cum, s, side="right") - 1, 0, len(g) - 2))
            t = (s - cum[k]) / max(cum[k + 1] - cum[k], 1e-12)
            return g[k] + (g[k + 1] - g[k]) * t, k

        pa, ka = at(f0)
        pb, kb = at(f1)
        pts = [pa] + [g[k] for k in range(ka + 1, kb + 1)] + [pb]
        out = []
        for q in pts:
            q = [round(float(q[0]), 7), round(float(q[1]), 7)]
            if not out or out[-1] != q:
                out.append(q)
        return out

    # ---- construction --------------------------------------------------------------------------------------------
    @classmethod
    def from_tables(cls, roads: pd.DataFrame, arcs, geometry: dict, version: str, proj=None) -> "RoadNetwork":
        """roads: road_segment_id, length_m, free_flow_speed_mph, highway, lanes (NaN ok), [lanes_assumed,
        represented_by, static_availability, gap]. arcs: iterable of (road_id, road_id). geometry: id -> [[lon, lat]]."""
        ids = roads.road_segment_id.astype(str).to_numpy()
        pos = {s: i for i, s in enumerate(ids)}
        rep = roads["represented_by"] if "represented_by" in roads else pd.Series([None] * len(roads))
        resource = np.arange(len(ids))
        n_alias, n_alias_missing = 0, 0
        for i, r in enumerate(rep.to_numpy()):
            if isinstance(r, str) and r:
                if r in pos:
                    resource[i] = pos[r]
                    n_alias += 1
                else:
                    n_alias_missing += 1
        arcs = list(arcs)
        pairs = {(pos[a], pos[b]) for a, b in arcs if a in pos and b in pos and a != b}
        a = np.array(sorted(pairs), np.int64).reshape(-1, 2)
        lanes = roads["lanes"].to_numpy(float) if "lanes" in roads else np.full(len(ids), np.nan)
        avail = (roads["static_availability"].to_numpy().astype(object) if "static_availability" in roads
                 else np.full(len(ids), "open", object))
        gap = roads["gap"].fillna("none").to_numpy().astype(object) if "gap" in roads else np.full(len(ids), "none", object)
        geo = [np.asarray(geometry[s], float) for s in ids]
        if proj is None:
            allpts = np.concatenate(geo)
            proj = (float(allpts[:, 0].mean()), float(allpts[:, 1].mean()))
        stats = {"roads": len(ids), "arcs_input": len(arcs), "arcs": len(a),
                 "arcs_dropped_unknown_or_self": len(arcs) - len(pairs), "aliases": n_alias,
                 "aliases_without_representative": n_alias_missing}
        return cls(ids=ids, length_m=roads.length_m.to_numpy(float),
                   free_flow_mph=roads.free_flow_speed_mph.to_numpy(float),
                   hw=np.array([hw_group(h) for h in roads.highway.astype(str)], object), lanes=lanes,
                   lanes_assumed=(roads["lanes_assumed"].to_numpy(bool) if "lanes_assumed" in roads
                                  else ~np.isfinite(lanes)),
                   resource=resource, static_availability=avail, gap=gap, src=a[:, 0].copy(), dst=a[:, 1].copy(),
                   geometry=geo, version=version, proj=proj, stats=stats)

    @classmethod
    def from_artifacts(cls, cfg: Config) -> "RoadNetwork":
        nc = cfg.network
        net_dir = cfg.path(nc.sim_root) / nc.network
        version, hashes = network_version(net_dir, nc.network)
        seg = pd.read_parquet(cfg.path(nc.segments))
        patch = json.loads(cfg.path(nc.patch).read_text())
        cw = pd.read_csv(net_dir / "crosswalk.csv").set_index("road_segment_id")
        arcs = [tuple(x) for x in json.loads((net_dir / "arcs_c90.json").read_text())]

        in_model = seg.in_sumo.to_numpy() & (seg.car_access == "yes").to_numpy()
        alias = (seg.gap == "merged_parallel").to_numpy() & seg.represented_by.notna().to_numpy()
        avail = np.where(in_model, "open", np.where(alias, "alias",
                         np.where(seg.in_sumo.to_numpy(), "restricted", "unavailable")))
        ids = seg.road_segment_id.astype(str)
        lanes = cw.reindex(ids)["lanes"].to_numpy(float, copy=True)      # writable under pandas copy-on-write
        lsrc = cw.reindex(ids)["lanes_source"].astype(object).to_numpy()
        pl = np.array([patch["segments"].get(s, {}).get("lanes") for s in ids], dtype=object)
        miss = ~np.isfinite(lanes)
        lanes[miss] = [float(x) if x is not None else np.nan for x in pl[miss]]
        roads = pd.DataFrame({
            "road_segment_id": ids, "length_m": seg.length_m, "free_flow_speed_mph": seg.free_flow_speed_mph,
            "highway": seg.highway, "lanes": lanes,
            "lanes_assumed": ~np.isfinite(lanes) | (lsrc != "osm"),
            "represented_by": seg.represented_by.where(alias, None), "static_availability": avail,
            "gap": seg.gap})
        geometry = {s: patch["segments"][s]["coords"] for s in ids}
        net = cls.from_tables(roads, arcs, geometry, version, proj=(patch["proj"]["lon0"], patch["proj"]["lat0"]))
        net.stats.update({"network_dir": str(net_dir), "file_sha256": hashes,
                          "segments_sha256": sha256_file(cfg.path(nc.segments)),
                          "static_availability": pd.Series(avail).value_counts().to_dict(),
                          "roads_without_in_arcs": int((net.indeg == 0).sum()),
                          "roads_without_out_arcs": int((net.outdeg == 0).sum()),
                          "alias_roads_with_arcs": int(((net.indeg + net.outdeg) > 0)[alias].sum())})
        return net
