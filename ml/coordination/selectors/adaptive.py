"""Policy E (default): adaptive. The heuristic handles normal traffic; requests whose fastest route is predicted to be
congested go to the learned policy (PPO checkpoint in `rl.checkpoint`).

Why: in the fireworks backtests (ml/reports/fireworks_*) PPO with the wider candidate search cut total travel time by
29-55% when most of an overloaded jam was coordinated, but made light traffic 2-5% worse (it almost never keeps the
fastest route); the heuristic never hurt much. So the switch is made per decision from what the forecaster predicts.

Stress of a request = predicted congestion ratio along its fastest valid candidate (duration-weighted `snap.cong`,
the RL feature `fc_congestion_mean`; 0 = free flow, 1 = stopped) and the mean ledger load ratio of that route (load /
allocation budget, the RL feature `load_ratio_mean`). A batch goes to the learned policy if any request has
congestion >= `stress` or load ratio >= `load`. Defaults 0.5 (speed <= 50% of free flow, the backtest's
"congested" definition) and 1.0 (route reserved over its budget): starting values, not tuned. If the checkpoint is
missing or incompatible the heuristic decides and the fallback is recorded; a request is never refused for it.

Optional light tier (`light`, `lload`; off by default, so `adaptive` is unchanged): when EVERY request of a batch has
congestion < `light` and load ratio < `lload`, the batch takes its fastest route (forecast_only). Rule 0 fireworks
runs (2026-09-27, ml/reports/rule0/) showed coordination only pays off from ~6,000 crowd cars upward and at >= 50%
participation; below that the fastest route was as good or better. The thresholds that correspond to that load
are NOT calibrated yet: set them on development scenarios (standard rule 6) before relying on them.
"""
from __future__ import annotations

import numpy as np

from ..schemas import SelectionContext, SelectionResult
from .base import Selector, SelectorUnavailable, valid_indices
from .forecast_only import ForecastOnly
from .heuristic import Heuristic
from .rl import RL


def route_stress(ctx: SelectionContext, item) -> tuple[float, float]:
    """(predicted congestion, ledger load ratio) along the fastest valid candidate of one request."""
    idx = valid_indices(item)
    if not idx or ctx.snapshot is None:
        return 0.0, 0.0
    c = item.candidates[min(idx, key=lambda j: (item.candidates[j].eta_s, item.candidates[j].candidate_id))]
    snap, tr = ctx.snapshot, c.timed
    dur = np.array([max(e.exit - e.entry, 0.0) for e in tr.entries])
    if not len(dur) or dur.sum() <= 0:
        cong = 0.0
    else:
        ks = np.clip([snap.bucket(e.entry) for e in tr.entries], 0, snap.H - 1)
        cg = np.nan_to_num(np.array([snap.cong[e.road, k] for e, k in zip(tr.entries, ks)], float))
        cong = float((cg * dur).sum() / dur.sum())
    budget = ctx.score_budget
    ratios = [ctx.base_load(cell) / max(float(budget[cell[0]]) if budget is not None else 1.0, 1e-6) for cell in c.cells]
    return cong, float(np.mean(ratios)) if ratios else 0.0


class Adaptive(Selector):
    name = "adaptive"
    version = "adaptive-v1"

    def __init__(self, cfg=None, stress: float = 0.5, load: float = 1.0, checkpoint: str | None = None,
                 light: float | None = None, lload: float = 0.5):
        self.cfg, self.stress, self.load = cfg, float(stress), float(load)
        self.light, self.lload = (None if light is None else float(light)), float(lload)
        self.heuristic = Heuristic()
        self.fastest = ForecastOnly()
        self.learned = RL(cfg, checkpoint=checkpoint)
        self.counts = {"fastest": 0, "heuristic": 0, "learned": 0, "learned_unavailable": 0}

    def select(self, ctx: SelectionContext) -> SelectionResult:
        levels = [route_stress(ctx, it) for it in ctx.items]
        high = any(cg >= self.stress or lr >= self.load for cg, lr in levels)
        light = self.light is not None and all(cg < self.light and lr < self.lload for cg, lr in levels)
        mode, why = "heuristic", None
        if light and not high:
            mode = "fastest"
        elif high:
            try:
                res = self.learned.select(ctx)
                mode = "learned"
            except SelectorUnavailable as e:        # never refuse a request because the learned policy is missing
                why = str(e)[:200]
                mode = "learned_unavailable"
        if mode == "fastest":
            res = self.fastest.select(ctx)
        elif mode != "learned":
            res = self.heuristic.select(ctx)
        self.counts[mode] += 1
        res.policy, res.policy_version = self.name, f"{self.version}:{mode}"
        diag = {"adaptive_mode": mode, "stress": [round(cg, 3) for cg, _ in levels],
                "load_ratio": [round(lr, 3) for _, lr in levels], "thresholds": [self.stress, self.load],
                "light_thresholds": [self.light, self.lload]}
        if why:
            diag["learned_unavailable"] = why
        for rid in res.choices:                     # own key: the per-request dict is keyed by candidate id
            res.diagnostics.setdefault(rid, {})["_adaptive"] = diag
        return res
