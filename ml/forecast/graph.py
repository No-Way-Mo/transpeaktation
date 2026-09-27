"""Road table, legal road-to-road connections, static road features and balanced spatial patches.

Nodes are directed canonical road segments (OSM u-v-key). Connections come from the selected SUMO network's
edge-to-edge connectivity (`arcs_c90.json`, built from the network's lane connections, so turn prohibitions in
patch.con.xml are respected). Coordinates are never used to invent connections.

* Roads without a SUMO edge (connectors absorbed into merged junctions, omitted self-loops) have no measurements and
  are not modelled: they are exported as `unavailable`. SUMO arcs already connect the roads on either side of an
  absorbed junction, so connectivity through merged junctions is preserved without fabricating their data.
* Roads barred for passenger cars (busway, access=no) are not modelled either and export as `restricted`.
* v3 `merged_parallel` roads (represented_by) are mapped explicitly if a v3 network is selected.

Everything sparse: edge lists / CSR, never an N x N matrix.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import Config, MPH_PER_MPS

HIGHWAY_GROUPS = ["motorway", "trunk", "primary", "secondary", "tertiary", "residential", "minor"]
STATIC_FEATURES = (["log_length_m", "log_free_flow_mph", "lanes", "lanes_assumed", "oneway", "signal_at_end",
                    "posted_limit", "heading_sin", "heading_cos", "x_km", "y_km", "log_in_degree", "log_out_degree",
                    "is_link"] + [f"hw_{g}" for g in HIGHWAY_GROUPS])


def _hw_group(h: str) -> str:
    h = h.replace("_link", "")
    return h if h in HIGHWAY_GROUPS else "minor"


@dataclass
class RoadGraph:
    roads: pd.DataFrame          # all canonical roads, segments.parquet order, with model_idx (-1 = not modelled)
    model_ids: np.ndarray        # [N] road ids of modelled roads (the model's road order)
    src: np.ndarray              # [E] legal arcs in model indices: road src can be followed by road dst
    dst: np.ndarray
    xy: np.ndarray               # [N, 2] local metres (road midpoints)
    length_m: np.ndarray
    free_flow_mph: np.ndarray
    static: np.ndarray           # [N, len(STATIC_FEATURES)] unnormalised
    patch_idx: np.ndarray        # [P, S] model index, -1 = padding
    road_patch: np.ndarray       # [N]
    stats: dict

    @property
    def n(self) -> int:
        return len(self.model_ids)

    @property
    def ref_tt_s(self) -> np.ndarray:
        return self.length_m / (self.free_flow_mph / MPH_PER_MPS)


def local_xy(lonlat: np.ndarray, lon0: float, lat0: float) -> np.ndarray:
    k = math.cos(math.radians(lat0))
    return np.stack([(lonlat[:, 0] - lon0) * 111_320.0 * k, (lonlat[:, 1] - lat0) * 110_540.0], 1)


def balanced_patches(xy: np.ndarray, size: int) -> list[np.ndarray]:
    """Recursive coordinate bisection with patch counts split proportionally: every leaf <= size, spatially compact,
    deterministic (ties broken by index)."""
    n = len(xy)
    P = max(1, math.ceil(n / size))
    while True:
        leaves: list[np.ndarray] = []

        def rec(idx: np.ndarray, p: int) -> None:
            if p == 1:
                leaves.append(idx)
                return
            pts = xy[idx]
            axis = int(np.ptp(pts[:, 1]) > np.ptp(pts[:, 0]))
            order = idx[np.lexsort((idx, pts[:, 1 - axis], pts[:, axis]))]
            pl = p // 2
            nl = len(idx) * pl // p
            rec(order[:nl], pl)
            rec(order[nl:], p - pl)

        rec(np.arange(n), P)
        if max(len(l) for l in leaves) <= size and min(len(l) for l in leaves) > 0:
            return leaves
        P += 1


def csr(n: int, src: np.ndarray, dst: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    order = np.argsort(src, kind="stable")
    ptr = np.zeros(n + 1, np.int64)
    np.add.at(ptr, src + 1, 1)
    return np.cumsum(ptr), dst[order]


def bfs_hops(n: int, src: np.ndarray, dst: np.ndarray, sources: np.ndarray, max_hops: int) -> np.ndarray:
    """Hops from any source following arcs src -> dst; max_hops + 1 = not reached within max_hops."""
    ptr, nbr = csr(n, src, dst)
    hops = np.full(n, max_hops + 1, np.int16)
    front = np.unique(sources)
    hops[front] = 0
    for h in range(1, max_hops + 1):
        if not len(front):
            break
        nxt = np.concatenate([nbr[ptr[i]:ptr[i + 1]] for i in front]) if len(front) else np.empty(0, np.int64)
        nxt = np.unique(nxt)
        nxt = nxt[hops[nxt] > h]
        hops[nxt] = h
        front = nxt
    return hops


def build(cfg: Config) -> RoadGraph:
    seg = pd.read_parquet(cfg.batch_dir / "export" / "segments.parquet")
    patch = json.loads((cfg.sim_root / "prepared" / "patch.json").read_text())
    cw = pd.read_csv(cfg.net_dir / "crosswalk.csv").set_index("road_segment_id")
    arcs = json.loads((cfg.net_dir / "arcs_c90.json").read_text())
    signals = set(patch["signals"])
    lon0, lat0 = patch["proj"]["lon0"], patch["proj"]["lat0"]

    model = seg.in_sumo.to_numpy() & (seg.car_access == "yes").to_numpy()
    roads = seg.copy()
    roads["model_idx"] = -1
    roads.loc[model, "model_idx"] = np.arange(model.sum())
    roads["availability_static"] = np.where(model, "open", np.where(seg.in_sumo, "restricted", "unavailable"))
    roads["represented_by"] = seg["represented_by"] if "represented_by" in seg.columns else None
    m = roads[model].reset_index(drop=True)
    ids = m.road_segment_id.to_numpy()
    pos = {s: i for i, s in enumerate(ids)}

    a = np.array([(pos[x], pos[y]) for x, y in arcs if x in pos and y in pos], np.int64).reshape(-1, 2)
    src, dst = a[:, 0], a[:, 1]
    prohibited = {tuple(p) for p in patch.get("turn_prohibitions", [])}
    arc_set = {(x, y) for x, y in arcs}
    n = len(ids)

    ps = [patch["segments"][s] for s in ids]
    mid = np.array([np.asarray(p["coords"], float).mean(0) for p in ps])
    first = local_xy(np.array([p["coords"][0] for p in ps], float), lon0, lat0)
    last = local_xy(np.array([p["coords"][-1] for p in ps], float), lon0, lat0)
    xy = local_xy(mid, lon0, lat0)
    head = np.arctan2(last[:, 1] - first[:, 1], last[:, 0] - first[:, 0])
    indeg = np.bincount(dst, minlength=n)
    outdeg = np.bincount(src, minlength=n)
    lanes = cw.loc[ids, "lanes"].to_numpy(float)
    hw = m.highway.astype(str).to_numpy()
    static = np.column_stack([
        np.log(np.maximum(m.length_m.to_numpy(), 1.0)),
        np.log(m.free_flow_speed_mph.to_numpy()),
        lanes,
        (m.lanes_source != "osm").to_numpy(float),
        np.array([bool(p.get("oneway")) for p in ps], float),
        np.array([p["v"] in signals for p in ps], float),
        (m.free_flow_source == "datasf_posted").to_numpy(float),
        np.sin(head), np.cos(head),
        xy[:, 0] / 1000.0, xy[:, 1] / 1000.0,
        np.log1p(indeg), np.log1p(outdeg),
        np.array(["_link" in h for h in hw], float),
        *[np.array([_hw_group(h) == g for h in hw], float) for g in HIGHWAY_GROUPS],
    ]).astype(np.float32)
    assert static.shape[1] == len(STATIC_FEATURES)

    leaves = balanced_patches(xy, cfg.graph.patch_size)
    S = cfg.graph.patch_size
    patch_idx = np.full((len(leaves), S), -1, np.int64)
    road_patch = np.full(n, -1, np.int64)
    for p, l in enumerate(leaves):
        patch_idx[p, :len(l)] = l
        road_patch[l] = p
    assert (road_patch >= 0).all()
    cross = int((road_patch[src] != road_patch[dst]).sum())
    stats = {"model_roads": n, "arcs_in_network": len(arcs), "arcs_between_model_roads": len(src),
             "arcs_dropped_non_model_endpoint": len(arcs) - len(src),
             "turn_prohibitions": len(prohibited), "prohibited_pairs_present_as_arcs": len(prohibited & arc_set),
             "roads_without_in_arcs": int((indeg == 0).sum()), "roads_without_out_arcs": int((outdeg == 0).sum()),
             "patches": len(leaves), "patch_size": S, "patch_fill_min": int(min(map(len, leaves))),
             "patch_fill_max": int(max(map(len, leaves))), "padding_slots": int((patch_idx < 0).sum()),
             "arcs_crossing_patches": cross}
    return RoadGraph(roads=roads, model_ids=ids, src=src, dst=dst, xy=xy.astype(np.float32),
                     length_m=m.length_m.to_numpy(float), free_flow_mph=m.free_flow_speed_mph.to_numpy(float),
                     static=static, patch_idx=patch_idx, road_patch=road_patch, stats=stats)


def save(g: RoadGraph, d) -> None:
    d.mkdir(parents=True, exist_ok=True)
    g.roads.to_parquet(d / "roads.parquet", index=False)
    np.savez(d / "graph.npz", model_ids=g.model_ids.astype(str), src=g.src, dst=g.dst, xy=g.xy, length_m=g.length_m,
             free_flow_mph=g.free_flow_mph, static=g.static, patch_idx=g.patch_idx, road_patch=g.road_patch)
    (d / "graph_stats.json").write_text(json.dumps(g.stats, indent=1))


def load(d) -> RoadGraph:
    z = np.load(d / "graph.npz")
    return RoadGraph(roads=pd.read_parquet(d / "roads.parquet"), model_ids=z["model_ids"], src=z["src"], dst=z["dst"],
                     xy=z["xy"], length_m=z["length_m"], free_flow_mph=z["free_flow_mph"], static=z["static"],
                     patch_idx=z["patch_idx"], road_patch=z["road_patch"],
                     stats=json.loads((d / "graph_stats.json").read_text()))
