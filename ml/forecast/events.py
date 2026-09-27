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


def _iso(ts: float | None) -> str | None:
    return None if ts is None else datetime.fromtimestamp(ts, timezone.utc).isoformat()


def _ts(s: str | None) -> float:
    return np.nan if s is None else datetime.fromisoformat(s).timestamp()


def run_context(sc: dict, run: dict) -> dict:
    """Scenario metadata -> portable context JSON (same format a live snapshot would provide)."""
    from .audit import local_to_utc
    fam = next(f for f in sc["families"] if f["family_id"] == run["family_id"])
    cases: dict[str, dict] = {}
    for r in run["restrictions"]:
        focal = r["source"] == "event_permit"
        c = cases.setdefault(r["case_num"], {
            "case_num": r["case_num"], "kind": "public_event" if focal else "permit",
            "public_start": None, "public_end": None, "declared_attendance": None,
            "declared_attendance_source": None, "restrictions": []})
        c["restrictions"].append({"segment_ids": r["segment_ids"], "restriction": r["restriction"],
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

    def to_torch(self, device) -> "EventTensors":
        f = lambda a: torch.as_tensor(np.asarray(a), device=device)
        return EventTensors(f(self.pair_case), f(self.pair_road), f(self.pair_static).float(),
                            f(self.pair_rbegin).double(), f(self.pair_rend).double(), f(self.case_static).float(),
                            f(self.case_times).double())

    @property
    def n_pairs(self) -> int:
        return len(self.pair_case)


def build_tensors(ctx: dict, graph: RoadGraph, cfg: Config, att_norm=(10.0, 1.0)) -> EventTensors:
    ec = cfg.events
    pos = {s: i for i, s in enumerate(graph.model_ids)}
    pc, pr, ps, pb, pe, cs, ct = [], [], [], [], [], [], []
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
    cat = lambda xs, dt, shape: np.concatenate(xs).astype(dt) if xs else np.zeros(shape, dt)
    return EventTensors(cat(pc, np.int64, 0), cat(pr, np.int64, 0), cat(ps, np.float32, (0, len(PAIR_STATIC))),
                        cat(pb, np.float64, 0), cat(pe, np.float64, 0),
                        np.asarray(cs, np.float32).reshape(-1, len(CASE_STATIC)),
                        np.asarray(ct, np.float64).reshape(-1, 4))


def pair_features(ev: EventTensors, bucket_start: torch.Tensor, bucket_s: int, clip_h: float) -> torch.Tensor:
    """[K] bucket starts (epoch s, double) -> [K, P, len(EVENT_PAIR_FEATURES)] float features at each bucket."""
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
    return torch.cat([ev.pair_static[None].expand(K, P, -1), ev.case_static[ev.pair_case][None].expand(K, P, -1),
                      case_t[:, ev.pair_case], cover], -1)
