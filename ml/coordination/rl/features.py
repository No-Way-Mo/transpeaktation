"""Shared, versioned observation encoder: the ONLY feature path for training, evaluation and serving.

obs = [K x per-candidate features] ++ [global features], float32; mask = [K] valid slots.

* Slot order is the coordinator's deterministic candidate order (forecast ETA, then path hash). Absent slots are
  zero-padded and masked. An all-false mask is never produced: requests without candidates are handled before
  any policy is asked.
* Every input is available at serving time: the candidates (timed on the current forecast), the forecast
  snapshot (issued at or before `now`; a later issue time raises LeakageError), the allocation ledger plus earlier
  choices of the current batch (overlay), the request itself and the clock. No simulator internals, no future
  traffic, no scenario labels.
* Normalisation uses FIXED physical scales (encoded in the feature names), so there are no running statistics
  to freeze or leak between train/validation/test.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np

from ..network import HIGHWAY_GROUPS
from ..schemas import SelectionContext
from ..scoring import delta_phi
from ..timing import overlap_share

SCHEMA_VERSION = "rl_obs_v1"
SF_TZ = ZoneInfo("America/Los_Angeles")

CAND_FEATURES = (["valid", "eta_per_10min", "distance_per_5km", "extra_per_180s", "extra_ratio_per_0.15",
                  "fc_congestion_mean", "fc_congestion_missing_share", "entries_per_50", "load_ratio_mean",
                  "load_ratio_max_per_4", "marginal_penalty_per_60s", "overlap_other_max", "overlap_fastest"]
                 + [f"exposure_share_{g}" for g in HIGHWAY_GROUPS]
                 + ["arrive_offset_per_1h", "depart_offset_per_10min"])
GLOBAL_FEATURES = ["tod_sin", "tod_cos", "forecast_age_per_10min", "batch_size_per_32", "batch_index_per_32",
                   "future_load_per_1000", "live_assignments_per_500", "origin_x_per_10km", "origin_y_per_10km",
                   "dest_x_per_10km", "dest_y_per_10km", "valid_count_per_k", "active_closures_per_100",
                   "forecast_is_fixture"]


class LeakageError(Exception):
    pass


def schema(k: int) -> dict:
    return {"version": SCHEMA_VERSION, "k": k, "candidate_features": CAND_FEATURES,
            "global_features": GLOBAL_FEATURES, "dim": obs_dim(k),
            "normalisation": "fixed physical scales (see feature names); no running statistics"}


def obs_dim(k: int) -> int:
    return k * len(CAND_FEATURES) + len(GLOBAL_FEATURES)


_closure_cache: dict = {}


def _active_closures(snap, now: float) -> int:
    key = (snap.version, int(now // 60))
    if key not in _closure_cache:
        if len(_closure_cache) > 256:
            _closure_cache.clear()
        _closure_cache[key] = sum(1 for cl in snap.closures.values() for b, e, _ in cl if b <= now < e)
    return _closure_cache[key]


def encode(ctx: SelectionContext, i: int, overlay: dict | None, k: int) -> tuple[np.ndarray, np.ndarray]:
    """Observation for request i of the context, given extra load from earlier choices in this batch."""
    snap, net = ctx.snapshot, ctx.net
    if snap is None or net is None:
        raise ValueError("SelectionContext lacks the policy context (snapshot/net); build it via the coordinator")
    if snap.issued_at > ctx.now + 1e-6:
        raise LeakageError(f"forecast issued at {snap.issued_at} is after the decision time {ctx.now}")
    item = ctx.items[i]
    cands = item.candidates
    valid_idx = [j for j, ok in enumerate(item.mask) if ok and j < k]
    if not valid_idx:
        raise ValueError("no valid candidate: handle the request outside the policy")
    overlay = overlay or {}
    fastest = item.fastest_eta_s
    bound = max(min(180.0, 0.15 * fastest), 1e-6)
    C = np.zeros((k, len(CAND_FEATURES)), np.float32)
    mask = np.zeros(k, bool)
    budget = ctx.score_budget
    for j, c in enumerate(cands[:k]):
        if not item.mask[j]:
            continue
        mask[j] = True
        tr = c.timed
        dur = np.array([max(e.exit - e.entry, 0.0) for e in tr.entries])
        tot = max(dur.sum(), 1e-6)
        ks = np.clip([snap.bucket(e.entry) for e in tr.entries], 0, snap.H - 1)
        cg = np.array([snap.cong[e.road, kk] for e, kk in zip(tr.entries, ks)])
        miss = ~np.isfinite(cg)
        cg_mean = float((np.nan_to_num(cg) * dur).sum() / tot)
        ratios = []
        for cell in c.cells:
            L = ctx.base_load(cell) + overlay.get(cell, 0.0)
            B = float(budget[cell[0]]) if budget is not None else 1.0
            ratios.append(L / max(B, 1e-6))
        ratios = np.asarray(ratios) if ratios else np.zeros(1)
        pen = delta_phi(c.cells, ctx.base_load, ctx.cell_coef, overlay) * ctx.lam
        others = [overlap_share(tr, x.timed) for jj, x in enumerate(cands[:k]) if jj != j and item.mask[jj]]
        expo = c.timed.class_exposure_s
        row = [1.0, c.eta_s / 600.0, tr.distance_m / 5000.0, (c.eta_s - fastest) / 180.0,
               (c.eta_s - fastest) / bound, cg_mean, float(miss.mean()) if len(miss) else 0.0,
               len(tr.entries) / 50.0, float(ratios.mean()), float(ratios.max()) / 4.0,
               min(pen / 60.0, 10.0), max(others) if others else 0.0, overlap_share(tr, cands[0].timed)]
        row += [expo.get(g, 0.0) / max(c.eta_s, 1e-6) for g in HIGHWAY_GROUPS]
        row += [(tr.arrive - ctx.now) / 3600.0, (tr.depart - ctx.now) / 600.0]
        C[j] = row
    lt = datetime.fromtimestamp(ctx.now, timezone.utc).astimezone(SF_TZ)
    h = (lt.hour * 3600 + lt.minute * 60 + lt.second) / 86400.0
    oxy = net.to_xy(np.asarray(item.request.origin, float))[0] / 10_000.0
    dxy = net.to_xy(np.asarray(item.request.destination, float))[0] / 10_000.0
    G = np.array([math.sin(2 * math.pi * h), math.cos(2 * math.pi * h), (ctx.now - snap.issued_at) / 600.0,
                  len(ctx.items) / 32.0, i / 32.0, ctx.ledger_future_load / 1000.0, ctx.ledger_live / 500.0,
                  oxy[0], oxy[1], dxy[0], dxy[1], mask.sum() / k, _active_closures(snap, ctx.now) / 100.0,
                  float(snap.fixture)], np.float32)
    obs = np.concatenate([C.ravel(), G]).astype(np.float32)
    if not np.all(np.isfinite(obs)):
        obs = np.nan_to_num(obs, nan=0.0, posinf=10.0, neginf=-10.0)
    return obs, mask
