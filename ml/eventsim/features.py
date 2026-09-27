"""Model-visible observations, baselines and features. Shared by dataset.py (offline) and replay.py (online).

Leakage rules enforced here:
  * features at forecast origin t use observations with bucket <= t only (ObsModel is causal);
  * the event is described by *declared* information: published closure schedule, declared public hours and a
    noisy (sometimes missing) vehicle-demand estimate; never the realised arrival curve, hidden demand, or
    simulator future states;
  * closures are known restrictions (routing rule), not predicted speeds.
"""
from __future__ import annotations

import math

import numpy as np

from .config import BUCKET_S, TILE_CONGESTION_RATIO

MIN_SPEED = 0.5         # m/s; floor used for travel times of (nearly) stopped segments
MAX_TT = 1800.0         # s; physical upper bound on one segment's travel time in a 10-min bucket
MIN_SAMPLED_S = 5.0     # vehicle-seconds in a bucket below which a segment counts as empty (no measurement)
FFILL_MAX = 2           # AGENTS.md: forward-fill <= 2 buckets, with masks, never from the future
CATS = ("low", "moderate", "heavy", "severe")
CAT_EDGES = (0.25, 0.5, 0.75)
CAT_RATIO = np.array([TILE_CONGESTION_RATIO[c] for c in CATS])

# Event-rule baseline (hand-written, fixed a priori, independent of the simulator; see evaluate.py).
RULE_ARRIVAL = 0.3, -60, 120     # amplitude, window start/end in minutes relative to declared start
RULE_DEPARTURE = 0.5, -30, 90    # relative to declared end
RULE_DECAY_M = 400.0
RULE_MAX_M = 1000.0

FEATURES = [
    "horizon_min", "tod_origin_min", "tod_target_min",
    "length_m", "lanes", "free_flow_mps", "road_rank", "oneway", "signal_at_end", "tomtom_covered",
    "dist_to_footprint_m", "heading_to_event_cos", "degree_in", "degree_out",
    "base_tt_ratio", "base_source", "tt_obs_age", "speed_ratio_l0", "speed_ratio_l1", "speed_ratio_l2",
    "speed_ratio_l3", "speed_trend", "cat_ratio_l0", "cat_age", "up_speed_ratio", "down_speed_ratio",
    "up_cat_ratio", "down_cat_ratio", "area_speed_ratio", "area_speed_ratio_l3", "area_cat_ratio",
    "event_declared", "min_from_declared_start", "min_to_declared_end", "in_arrival_window",
    "in_departure_window", "event_vehicle_estimate", "closed_within_300m_target", "closed_within_300m_origin",
    "closures_active_target",
]


class Static:
    """Per-segment static attributes (arrays aligned with Context.seg_ids)."""

    def __init__(self, ctx):
        seg = ctx.patch["segments"]
        ids = ctx.seg_ids
        self.n = len(ids)
        self.length = ctx.length
        self.ff_speed = ctx.ff_speed
        self.ff_tt = self.length / self.ff_speed
        self.lanes = np.array([max(ctx.lanes[s], 1) for s in ids], float)
        self.rank = np.array([seg[s]["rank"] for s in ids], float)
        self.oneway = np.array([seg[s]["oneway"] for s in ids], float)
        self.signal = np.array([seg[s]["signal_at_v"] for s in ids], float)
        self.tomtom = np.array([seg[s]["tomtom_line"] for s in ids], bool)
        self.dist = np.array([seg[s]["dist_to_footprint_m"] for s in ids], float)
        self.in_sim = ctx.in_sim
        lon0, lat0 = ctx.patch["proj"]["lon0"], ctx.patch["proj"]["lat0"]
        kx = math.radians(1) * 6371008.8 * math.cos(math.radians(lat0))
        ky = math.radians(1) * 6371008.8
        coords = [np.asarray(seg[s]["coords"]) for s in ids]
        mid = np.array([[(c[:, 0].mean() - lon0) * kx, (c[:, 1].mean() - lat0) * ky] for c in coords])
        vec = np.array([[(c[-1, 0] - c[0, 0]) * kx, (c[-1, 1] - c[0, 1]) * ky] for c in coords])
        closed_ids = [ctx.idx[c["segment_id"]] for c in ctx.patch["closure_edges"]]
        to_c = mid[closed_ids].mean(0) - mid   # towards the event footprint centre
        nv = np.linalg.norm(vec, axis=1) * np.linalg.norm(to_c, axis=1)
        self.heading_cos = np.where(nv > 0, (vec * to_c).sum(1) / np.maximum(nv, 1e-9), 0.0)
        # neighbourhoods
        by_u, by_v = {}, {}
        for i, s in enumerate(ids):
            by_u.setdefault(seg[s]["u"], []).append(i)
            by_v.setdefault(seg[s]["v"], []).append(i)
        self.up = [by_v.get(seg[s]["u"], []) for s in ids]      # segments feeding into this one
        self.down = [by_u.get(seg[s]["v"], []) for s in ids]    # segments this one feeds
        self.deg_in = np.array([len(x) for x in self.up], float)
        self.deg_out = np.array([len(x) for x in self.down], float)
        d2 = ((mid[:, None, :] - mid[None, :, :]) ** 2).sum(2)
        self.near300 = (d2 <= 300.0 ** 2).astype(np.float32)
        self.area = self.dist <= 300.0
        self.up_m = _adj_matrix(self.up, self.n)
        self.down_m = _adj_matrix(self.down, self.n)


def _adj_matrix(lists, n) -> np.ndarray:
    m = np.zeros((n, n), np.float32)
    for i, js in enumerate(lists):
        m[i, js] = 1.0
    return m


def true_travel_time(speed: np.ndarray, sampled: np.ndarray, length: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Measured segment travel time [s] from mean speed on the canonical length, and a 'measured' mask.

    Empty buckets (no vehicle) are *not* measurements: tt is NaN there, never an empty-road default.
    Stopped segments use the MIN_SPEED floor and are capped at MAX_TT.
    """
    ok = np.isfinite(speed) & (np.nan_to_num(sampled) >= MIN_SAMPLED_S)
    tt = np.where(ok, np.minimum(length / np.maximum(np.nan_to_num(speed), MIN_SPEED), MAX_TT), np.nan)
    return tt, ok


def category_of(ratio: np.ndarray) -> np.ndarray:
    return np.digitize(ratio, CAT_EDGES)


class ObsModel:
    """Causal generator of provider-like observations from simulated truth.

    tomtom: noisy speed, only on segments with a real TomTom line in the patch, randomly missing, sometimes stale.
    mapbox: congestion category on every segment, only every other bucket (20-min tiles); an empty segment shows
            'low' (what the provider displays), which is a category, not a speed.
    """

    def __init__(self, st: Static, params: dict, seed: int, n_buckets: int):
        self.st, self.p = st, params
        self.rng = np.random.default_rng(seed)
        self.phase = int(self.rng.integers(2))
        n, T = st.n, n_buckets
        self.speed = np.full((T, n), np.nan, np.float32)   # observed tomtom speed (m/s), as reported at bucket t
        self.cat = np.full((T, n), np.nan, np.float32)     # observed category index
        self.t = -1

    def observe(self, b: int, speed_row: np.ndarray, measured_row: np.ndarray) -> None:
        assert b == self.t + 1, "observations must be generated in time order"
        st, p, r = self.st, self.p, self.rng
        noise = np.exp(r.normal(0, p["speed_noise_sigma"], st.n))
        present = st.tomtom & measured_row & (r.random(st.n) >= p["tomtom_missing"])
        obs = np.where(present, np.nan_to_num(speed_row) * noise, np.nan)
        if b > 0:
            stale = r.random(st.n) < p["stale_prob"]
            obs = np.where(stale, self.speed[b - 1], obs)   # provider repeats its previous value
        self.speed[b] = obs
        if (b + self.phase) % 2 == 0:
            ratio = 1 - np.nan_to_num(speed_row) / st.ff_speed + r.normal(0, 0.1, st.n)
            c = category_of(np.clip(ratio, 0, 1)).astype(np.float32)
            self.cat[b] = np.where(measured_row, c, 0.0)
        self.t = b


def _latest(arr: np.ndarray, t: int, max_age: int) -> tuple[np.ndarray, np.ndarray]:
    """Most recent non-NaN value at or before t within max_age buckets, and its age (NaN if none)."""
    n = arr.shape[1]
    val = np.full(n, np.nan)
    age = np.full(n, np.nan)
    for a in range(max_age + 1):
        if t - a < 0:
            break
        row = arr[t - a]
        take = np.isnan(val) & ~np.isnan(row)
        val[take] = row[take]
        age[take] = a
    return val, age


def _nbr_mean(m: np.ndarray, x: np.ndarray) -> np.ndarray:
    ok = ~np.isnan(x)
    s = m @ np.where(ok, x, 0.0)
    c = m @ ok.astype(np.float32)
    return np.where(c > 0, s / np.maximum(c, 1), np.nan)


def persistence(st: Static, obs: ObsModel, t: int) -> tuple[np.ndarray, np.ndarray]:
    """'Same as now' travel time per segment from observations <= t: TomTom speed (ffill <= 2), else
    category-derived speed, else posted free flow. Returns (tt, source 0/1/2)."""
    sp, _ = _latest(obs.speed, t, FFILL_MAX)
    cat, _ = _latest(obs.cat, t, FFILL_MAX + 1)  # 20-min cadence: allow one more bucket
    cat_speed = st.ff_speed * (1 - CAT_RATIO[np.nan_to_num(cat).astype(int)])
    tt = np.where(~np.isnan(sp), st.length / np.maximum(sp, MIN_SPEED),
                  np.where(~np.isnan(cat), st.length / np.maximum(cat_speed, MIN_SPEED), st.ff_tt))
    src = np.where(~np.isnan(sp), 0, np.where(~np.isnan(cat), 1, 2))
    return np.minimum(tt, MAX_TT), src


def event_rule(st: Static, base_tt: np.ndarray, target_s: float, declared: tuple[float, float] | None) -> np.ndarray:
    """Persistence x (1 + amplitude(t) * exp(-d / 400 m)) near the declared event; hand-written, not learned."""
    if declared is None:
        return base_tt
    m = (target_s - declared[0]) / 60
    me = (target_s - declared[1]) / 60
    amp = 0.0
    if RULE_ARRIVAL[1] <= m <= RULE_ARRIVAL[2]:
        amp = max(amp, RULE_ARRIVAL[0])
    if RULE_DEPARTURE[1] <= me <= RULE_DEPARTURE[2]:
        amp = max(amp, RULE_DEPARTURE[0])
    w = np.where(st.dist <= RULE_MAX_M, np.exp(-st.dist / RULE_DECAY_M), 0.0)
    return np.minimum(base_tt * (1 + amp * w), MAX_TT)


def tt_bounds(st: Static) -> tuple[np.ndarray, np.ndarray]:
    return st.length / (1.3 * st.ff_speed), np.minimum(st.length / MIN_SPEED, MAX_TT)


def build_features(st: Static, obs: ObsModel, t: int, h: int, *, sim_begin_s: float, closed: np.ndarray,
                   declared: tuple[float, float] | None, event_estimate: float, base: tuple[np.ndarray, np.ndarray]
                   ) -> np.ndarray:
    """Feature matrix [segments x FEATURES] for origin bucket t and horizon h buckets.

    `closed` is the *published* closure schedule [bucket x segment] (known in advance), so its value at t+h is legit.
    """
    n = st.n
    origin_s = sim_begin_s + (t + 1) * BUCKET_S          # forecast issued at the end of bucket t
    target_s = sim_begin_s + (t + h) * BUCKET_S + BUCKET_S / 2
    base_tt, src = base
    ratio = obs.speed / st.ff_speed
    lags = [ratio[t - k] if t - k >= 0 else np.full(n, np.nan) for k in range(4)]
    sp, sp_age = _latest(obs.speed, t, FFILL_MAX)
    sp_ratio = sp / st.ff_speed
    cat, cat_age = _latest(obs.cat, t, FFILL_MAX + 1)
    cat_ratio = np.where(np.isnan(cat), np.nan, CAT_RATIO[np.nan_to_num(cat).astype(int)])
    area = lambda x: np.nanmean(np.where(st.area, x, np.nan)) if np.any(st.area & ~np.isnan(x)) else np.nan
    sp_l3, _ = _latest(obs.speed, t - 3, FFILL_MAX) if t >= 3 else (np.full(n, np.nan), None)
    tb = min(t + h, closed.shape[0] - 1)
    ev = declared is not None
    cols = {
        "horizon_min": np.full(n, h * 10.0),
        "tod_origin_min": np.full(n, origin_s / 60), "tod_target_min": np.full(n, target_s / 60),
        "length_m": st.length, "lanes": st.lanes, "free_flow_mps": st.ff_speed, "road_rank": st.rank,
        "oneway": st.oneway, "signal_at_end": st.signal, "tomtom_covered": st.tomtom.astype(float),
        "dist_to_footprint_m": st.dist, "heading_to_event_cos": st.heading_cos,
        "degree_in": st.deg_in, "degree_out": st.deg_out,
        "base_tt_ratio": base_tt / st.ff_tt, "base_source": src.astype(float), "tt_obs_age": sp_age,
        "speed_ratio_l0": lags[0], "speed_ratio_l1": lags[1], "speed_ratio_l2": lags[2], "speed_ratio_l3": lags[3],
        "speed_trend": sp_ratio - sp_l3 / st.ff_speed, "cat_ratio_l0": cat_ratio, "cat_age": cat_age,
        "up_speed_ratio": _nbr_mean(st.up_m, sp_ratio), "down_speed_ratio": _nbr_mean(st.down_m, sp_ratio),
        "up_cat_ratio": _nbr_mean(st.up_m, cat_ratio), "down_cat_ratio": _nbr_mean(st.down_m, cat_ratio),
        "area_speed_ratio": np.full(n, area(sp_ratio)), "area_speed_ratio_l3": np.full(n, area(sp_l3 / st.ff_speed)),
        "area_cat_ratio": np.full(n, area(cat_ratio)),
        "event_declared": np.full(n, float(ev)),
        "min_from_declared_start": np.full(n, (target_s - declared[0]) / 60 if ev else np.nan),
        "min_to_declared_end": np.full(n, (declared[1] - target_s) / 60 if ev else np.nan),
        "in_arrival_window": np.full(n, float(ev and RULE_ARRIVAL[1] <= (target_s - declared[0]) / 60 <= RULE_ARRIVAL[2])),
        "in_departure_window": np.full(n, float(ev and RULE_DEPARTURE[1] <= (target_s - declared[1]) / 60 <= RULE_DEPARTURE[2])),
        "event_vehicle_estimate": np.full(n, event_estimate),
        "closed_within_300m_target": st.near300 @ closed[tb].astype(np.float32),
        "closed_within_300m_origin": st.near300 @ closed[t].astype(np.float32),
        "closures_active_target": np.full(n, float(closed[tb].sum())),
    }
    return np.column_stack([cols[f] for f in FEATURES]).astype(np.float32)


def declared_estimate(fam: dict, with_event: bool, rng: np.random.Generator) -> float:
    """What an operator would *declare* about event vehicle demand: a perturbed estimate, sometimes missing."""
    if not with_event:
        return 0.0
    p = fam["observation"]
    if rng.random() < p["event_estimate_missing"]:
        return np.nan
    true_n = fam["event"]["vehicle_trips"] * fam["event"]["turnout_factor"]
    # the declared figure ignores turnout surprises: it is based on the planned size
    return float(fam["event"]["vehicle_trips"] * math.exp(rng.normal(0, p["event_estimate_sigma"]))) if true_n else 0.0
