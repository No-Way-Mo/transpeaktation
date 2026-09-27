"""Structured event context known at prediction time.

A run's context is a list of *cases*: the focal public event (event runs only) and every concurrent permit whose
restrictions apply to the run. Built only from frozen scenario metadata and reviewed closure footprints:

    kind                  public_event | permit
    public_start/end      scheduled public hours (focal event only; permits have none)
    restrictions          reviewed road footprint + scheduled begin/end (UTC)
    declared_attendance   an explicitly declared estimate, else null (+ missing flag)

Not used: the attendance / vehicle counts sampled for the run, arrival curves, driver or routing parameters, future
traffic, the paired run's outputs. In b2_bench concurrent permit cases are simulated as closures only (no attendee
demand), so they are encoded as `permit`, not as public events. Declared attendance = the event pool's published
`attendance_claim` (organiser/press figure with a source URL, v3 batches) for the focal event; where no claim was
found (or in v2 batches, whose ranges are unsourced assumptions) it is missing and flagged.

Each case is expanded to sparse (case, road) pairs for roads within `context_radius_m` of its footprint; features of
a pair depend on the road's relation to the footprint (distance, up/downstream hops over legal connections) and on
the bucket being predicted (time to public start/end, scheduled restrictions). The model aggregates pairs per road
with a permutation-invariant sum/max, so any number of concurrent cases is supported.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
import torch
from scipy.spatial import cKDTree

from .config import Config
from .graph import RoadGraph, bfs_hops

PAIR_STATIC = ["is_footprint", "prox_300m", "prox_1000m", "prox_3000m", "feeds_footprint_hop_prox", "fed_by_footprint_hop_prox"]
CASE_STATIC = ["is_public_event", "is_permit_only", "has_public_hours", "declared_attendance_log",
               "declared_attendance_missing"]
CASE_TIME = ["h_to_public_start", "h_to_public_end", "public_active", "h_to_restriction_begin",
             "h_to_restriction_end", "case_restriction_active"]
PAIR_TIME = ["road_restricted_by_case"]
EVENT_PAIR_FEATURES = PAIR_STATIC + CASE_STATIC + CASE_TIME + PAIR_TIME
# optional extensions, appended after the base features (checkpoint migration copies the base columns by position)
ROUTE_FEATURES = ["route_in_load", "route_out_load"]     # network-only shortest-path load toward / away from footprint
ONSET_FEATURES = ["onset_near_z_last", "onset_near_z_mean3", "onset_near_z_slope", "onset_near_cong_last"]
ROUTE_DECAY_M = 5000.0      # origin weight exp(-distance / decay) for the route loads (network assumption, no run data)
NEAR_PROX = float(np.exp(-1.0))   # prox_1000m >= this <=> within 1 km of the footprint
_ROUTE_CACHE: dict = {}
# DIAGNOSTIC ONLY (upper bound of what schedule context could explain): the focal event's hidden per-run sampler
# parameters. Never available at prediction time; a model using them must not be deployed.
ORACLE_FEATURES = ["oracle_arrival_offset_h", "oracle_arrival_sigma_h", "oracle_log_vehicles", "oracle_parking_km",
                   "oracle_departure_surge_share", "oracle_departure_sigma_h", "oracle_ridehail_share"]


def oracle_vector(fam: dict) -> list[float]:
    e = fam["event"]
    return [e["arrival_offset_min"] / 60, e["arrival_sigma_min"] / 60, float(np.log1p(e["vehicle_trips"])) / 10,
            e["parking_radius_m"][1] / 1000, e["departure_surge_share"], e["departure_surge_sigma_min"] / 60,
            e["ridehail_share"]]


def event_feature_names(cfg) -> list[str]:
    m = cfg.model
    return EVENT_PAIR_FEATURES + (ROUTE_FEATURES if getattr(m, "route_features", None) else []) + \
        (ONSET_FEATURES if getattr(m, "onset_features", None) else []) + \
        (ORACLE_FEATURES if getattr(m, "oracle_features", None) else [])


def route_loads(graph: RoadGraph, fp: np.ndarray, decay_m: float = ROUTE_DECAY_M) -> tuple[np.ndarray, np.ndarray]:
    """[N] shares of distance-weighted shortest-path demand that passes each road on the way INTO the footprint
    (from every road, weight exp(-dist/decay)) and OUT of it (to every road). Free-flow travel time weights; legal
    connections only. Network data only: no simulated demand, no per-run parameters."""
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import dijkstra
    n = graph.n
    tt = graph.ref_tt_s
    d_m = np.linalg.norm(graph.xy - graph.xy[fp].mean(0), axis=1)
    out = []
    for into in (True, False):
        # into the footprint = search from the footprint over reversed connections (arc a->b costs the time of a)
        a, b = (graph.dst, graph.src) if into else (graph.src, graph.dst)
        g = csr_matrix((np.maximum(tt[b] if into else tt[b], 1e-3), (a, b)), shape=(n, n))
        dist, pred, _ = dijkstra(g, directed=True, indices=fp, min_only=True, return_predecessors=True)
        ok = np.isfinite(dist)
        load = np.where(ok, np.exp(-d_m / decay_m), 0.0)
        for i in np.argsort(-np.where(ok, dist, -1.0)):      # farthest first: push each road's load to its parent
            p = pred[i]
            if ok[i] and p >= 0:
                load[p] += load[i]
        out.append(load / max(load.sum(), 1e-9))
    return out[0], out[1]


def _iso(ts: float | None) -> str | None:
    return None if ts is None else datetime.fromtimestamp(ts, timezone.utc).isoformat()


def _ts(s: str | None) -> float:
    return np.nan if s is None else datetime.fromisoformat(s).timestamp()


def run_context(sc: dict, run: dict) -> dict:
    """Scenario metadata -> portable context JSON (same format a live snapshot would provide)."""
    from .audit import local_to_utc, represented_map, with_represented
    fam = next(f for f in sc["families"] if f["family_id"] == run["family_id"])
    rep = represented_map(sc)   # closed merged carriageways are simulated on the edge that represents them
    cases: dict[str, dict] = {}
    for r in run["restrictions"]:
        focal = r["source"] == "event_permit"
        c = cases.setdefault(r["case_num"], {
            "case_num": r["case_num"], "kind": "public_event" if focal else "permit",
            "public_start": None, "public_end": None, "declared_attendance": None,
            "declared_attendance_source": None, "restrictions": []})
        c["restrictions"].append({"segment_ids": with_represented(r["segment_ids"], rep), "restriction": r["restriction"],
                                  "begin": local_to_utc(fam["date"], r["begin_s"]).isoformat(),
                                  "end": local_to_utc(fam["date"], r["end_s"]).isoformat(),
                                  "review_reason": r.get("review_reason")})
    if run["with_event"]:
        c = cases.setdefault(fam["case_num"], {"case_num": fam["case_num"], "kind": "public_event",
                                               "declared_attendance": None, "declared_attendance_source": None,
                                               "restrictions": []})
        c["kind"] = "public_event"
        c["event_key"] = fam["event_key"]
        pool = sc.get("event_pool", {}).get(fam["event_key"], {})
        if pool.get("attendance_claim"):   # a published figure with a source URL, not the run's sampled attendance
            c["declared_attendance"] = float(pool["attendance_claim"])
            c["declared_attendance_source"] = pool.get("attendance_source")
        c["public_start"] = local_to_utc(fam["date"], fam["public_hours_s"][0]).isoformat()
        c["public_end"] = local_to_utc(fam["date"], fam["public_hours_s"][1]).isoformat()
        c["public_hours_source"] = fam.get("sourced", {}).get("public_hours")
    return {"cases": sorted(cases.values(), key=lambda c: (c["kind"] != "public_event", c["case_num"])),
            "note": "scheduled context only; no realised demand"}


def focal_footprint(ctx: dict, graph: RoadGraph) -> np.ndarray:
    pos = {s: i for i, s in enumerate(graph.model_ids)}
    ids = {s for c in ctx["cases"] if c["kind"] == "public_event" for r in c["restrictions"] for s in r["segment_ids"]}
    return np.array(sorted(pos[s] for s in ids if s in pos), np.int64)


@dataclass
class EventTensors:
    pair_case: np.ndarray      # [P]
    pair_road: np.ndarray      # [P]
    pair_static: np.ndarray    # [P, len(PAIR_STATIC)]
    pair_rbegin: np.ndarray    # [P] epoch s (nan = road not restricted by this case)
    pair_rend: np.ndarray
    case_static: np.ndarray    # [C, len(CASE_STATIC)]
    case_times: np.ndarray     # [C, 4] public_start, public_end, first restriction begin, last restriction end
    pair_route: np.ndarray | None = None   # [P, 2] ROUTE_FEATURES (route_features models only)
    case_oracle: np.ndarray | None = None  # [C, len(ORACLE_FEATURES)] diagnostic-only models

    def to_torch(self, device) -> "EventTensors":
        f = lambda a: torch.as_tensor(np.asarray(a), device=device)
        return EventTensors(f(self.pair_case), f(self.pair_road), f(self.pair_static).float(),
                            f(self.pair_rbegin).double(), f(self.pair_rend).double(), f(self.case_static).float(),
                            f(self.case_times).double(),
                            None if self.pair_route is None else f(self.pair_route).float(),
                            None if self.case_oracle is None else f(self.case_oracle).float())

    @property
    def n_pairs(self) -> int:
        return len(self.pair_case)


def build_tensors(ctx: dict, graph: RoadGraph, cfg: Config, att_norm=(10.0, 1.0)) -> EventTensors:
    ec = cfg.events
    pos = {s: i for i, s in enumerate(graph.model_ids)}
    pc, pr, ps, pb, pe, cs, ct, prt = [], [], [], [], [], [], [], []
    want_route = bool(getattr(cfg.model, "route_features", None))
    for ci, c in enumerate(ctx["cases"]):
        fp_intervals: dict[int, list[float]] = {}
        for r in c["restrictions"]:
            if r.get("restriction", "full") != "full":
                continue
            b, e = _ts(r["begin"]), _ts(r["end"])
            for s in r["segment_ids"]:
                if s in pos:   # footprint pieces without a modelled road (absorbed connectors) carry no road pair
                    iv = fp_intervals.setdefault(pos[s], [b, e])
                    iv[0], iv[1] = min(iv[0], b), max(iv[1], e)
        fp = np.array(sorted(fp_intervals), np.int64)
        att = c.get("declared_attendance")
        cs.append([c["kind"] == "public_event", c["kind"] != "public_event", c.get("public_start") is not None,
                   0.0 if att is None else (np.log(att) - att_norm[0]) / att_norm[1], att is None])
        rb = [v[0] for v in fp_intervals.values()]
        re_ = [v[1] for v in fp_intervals.values()]
        ct.append([_ts(c.get("public_start")), _ts(c.get("public_end")),
                   min(rb) if rb else np.nan, max(re_) if re_ else np.nan])
        if not len(fp):
            continue
        d, _ = cKDTree(graph.xy[fp]).query(graph.xy, k=1)
        near = np.flatnonzero(d <= ec.context_radius_m)
        down = bfs_hops(graph.n, graph.src, graph.dst, fp, ec.max_hops)   # roads downstream of the footprint
        up = bfs_hops(graph.n, graph.dst, graph.src, fp, ec.max_hops)     # roads upstream (lead into it)
        H = ec.max_hops + 1
        is_fp = np.zeros(graph.n, bool)
        is_fp[fp] = True
        feats = np.column_stack([is_fp[near], *[np.exp(-d[near] / s) for s in ec.distance_scales_m],
                                 (H - up[near]) / H, (H - down[near]) / H])
        rbeg = np.array([fp_intervals.get(i, [np.nan, np.nan])[0] for i in near])
        rend = np.array([fp_intervals.get(i, [np.nan, np.nan])[1] for i in near])
        pc.append(np.full(len(near), ci)); pr.append(near); ps.append(feats); pb.append(rbeg); pe.append(rend)
        if want_route:   # scaled log share (x N, so a uniform share is log 2); cached per footprint
            key = (id(graph), fp.tobytes())
            if key not in _ROUTE_CACHE:
                _ROUTE_CACHE[key] = route_loads(graph, fp)
            li, lo = _ROUTE_CACHE[key]
            prt.append(np.column_stack([np.log1p(li[near] * graph.n), np.log1p(lo[near] * graph.n)]))
    cat = lambda xs, dt, shape: np.concatenate(xs).astype(dt) if xs else np.zeros(shape, dt)
    return EventTensors(cat(pc, np.int64, 0), cat(pr, np.int64, 0), cat(ps, np.float32, (0, len(PAIR_STATIC))),
                        cat(pb, np.float64, 0), cat(pe, np.float64, 0),
                        np.asarray(cs, np.float32).reshape(-1, len(CASE_STATIC)),
                        np.asarray(ct, np.float64).reshape(-1, 4),
                        cat(prt, np.float32, (0, len(ROUTE_FEATURES))) if want_route else None)


def onset_features(ev: EventTensors, hist: torch.Tensor) -> torch.Tensor:
    """[C, 4] recent traffic near each case's footprint from the (normalised) history [T, N, F]: valid-weighted mean z
    over roads within 1 km in the last bucket, the last 3 buckets, their slope (last - first bucket), and mean
    congestion in the last bucket. Causal: history buckets only."""
    from .data import HIST_FEATURES
    iz, ic, im = (HIST_FEATURES.index("z_filled"), HIST_FEATURES.index("congestion_filled"),
                  HIST_FEATURES.index("missing_after_fill"))
    C = ev.case_static.shape[0]
    out = hist.new_zeros(C, len(ONSET_FEATURES))
    if ev.n_pairs == 0:
        return out
    near = ev.pair_static[:, PAIR_STATIC.index("prox_1000m")] >= NEAR_PROX - 1e-6
    pc, pr = ev.pair_case[near], ev.pair_road[near]
    h = hist[:, pr].float()                                  # [T, P', F]
    valid = 1.0 - h[..., im]
    z, cg = h[..., iz] * valid, h[..., ic] * valid

    def cmean(x, v):   # per case, valid-weighted
        num = x.new_zeros(C).index_add_(0, pc, x)
        den = v.new_zeros(C).index_add_(0, pc, v)
        return num / den.clamp(min=1.0)
    last, first = cmean(z[-1], valid[-1]), cmean(z[0], valid[0])
    m3 = cmean(z[-3:].sum(0), valid[-3:].sum(0))
    return torch.stack([last, m3, last - first, cmean(cg[-1], valid[-1])], -1)


def pair_features(ev: EventTensors, bucket_start: torch.Tensor, bucket_s: int, clip_h: float,
                  onset: torch.Tensor | None = None) -> torch.Tensor:
    """[K] bucket starts (epoch s, double) -> [K, P, n] float features at each bucket (base EVENT_PAIR_FEATURES, then
    ROUTE_FEATURES if the tensors carry them, then ONSET_FEATURES if `onset` [C, 4] is given)."""
    t0 = bucket_start.double()[:, None]
    mid = t0 + bucket_s / 2
    ctm = ev.case_times[None]                                                   # [1, C, 4]

    def rel(ts):   # hours from bucket midpoint to ts, clipped and scaled to [-1, 1]; 0 when unknown
        return torch.nan_to_num(((ts - mid) / 3600.0).clamp(-clip_h, clip_h) / clip_h, nan=0.0)

    ps_, pe_ = ctm[..., 0], ctm[..., 1]
    rb, re_ = ctm[..., 2], ctm[..., 3]
    case_t = torch.stack([rel(ps_), rel(pe_), ((mid >= ps_) & (mid < pe_)).double(), rel(rb), rel(re_),
                          ((mid >= rb) & (mid < re_)).double()], -1).float()   # [K, C, 6]
    cover = ((torch.minimum(t0 + bucket_s, ev.pair_rend[None]) - torch.maximum(t0, ev.pair_rbegin[None])) / bucket_s)
    cover = torch.nan_to_num(cover.clamp(0, 1), nan=0.0).float()[..., None]    # [K, P, 1]
    K, P = t0.shape[0], ev.n_pairs
    parts = [ev.pair_static[None].expand(K, P, -1), ev.case_static[ev.pair_case][None].expand(K, P, -1),
             case_t[:, ev.pair_case], cover]
    if ev.pair_route is not None:
        parts.append(ev.pair_route[None].expand(K, P, -1))
    if onset is not None:
        parts.append(onset.float()[ev.pair_case][None].expand(K, P, -1))
    if ev.case_oracle is not None:
        parts.append(ev.case_oracle[ev.pair_case][None].expand(K, P, -1))
    return torch.cat(parts, -1)
