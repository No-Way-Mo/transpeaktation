"""Shared concentration penalty used by every coordinating selector and by the exact re-scoring of batch plans.

    Phi(L) = sum[e,b] w[e] * (L[e,b] / B[e])^2
    score(route) = ETA(route) + lambda * [Phi(L + route) - Phi(L)]

* L: participating entries per allocation resource and bin (ledger.py).
* B[e]: a POLICY budget of participating entries per bin = lanes x budget_per_lane[class]. Initialised from the
  documented class/lane assumptions in the config; not a measured residual capacity, never 1 - congestion.
  Missing lanes use default_lanes[class] and are counted in `assumptions()`.
* w[e] = class_sensitivity x free-flow seconds on the road / exposure_ref_s, so splitting one road into two halves
  leaves the penalty unchanged (limits sensitivity to arbitrary graph segmentation).
* lambda converts the penalty to seconds-equivalent SELECTION units. It is not predicted extra delay and is never
  reported as ETA.
"""
from __future__ import annotations

import hashlib

import numpy as np

from .config import ScoreCfg
from .network import RoadNetwork


class ConcentrationScore:
    def __init__(self, net: RoadNetwork, cfg: ScoreCfg):
        self.cfg = cfg
        lanes = net.lanes.copy()
        miss = ~np.isfinite(lanes) | (lanes <= 0)
        lanes[miss] = [cfg.default_lanes.get(h, 1) for h in net.hw[miss]]
        self.lanes_defaulted = int(miss.sum())
        budget = lanes * np.array([cfg.budget_per_lane.get(h, cfg.budget_per_lane.get("minor", 6.0)) for h in net.hw])
        sens = np.array([cfg.class_sensitivity.get(h, 1.0) for h in net.hw])
        w = sens * net.ff_tt_s / cfg.exposure_ref_s
        self.coef_road = w / np.maximum(budget, 1e-6) ** 2
        self.budget = budget

    def coef(self, cell) -> float:
        return float(self.coef_road[cell[0]])

    def assumptions(self) -> dict:
        return {"budget": "lanes x budget_per_lane[class] participating entries per bin (policy assumption)",
                "budget_per_lane": self.cfg.budget_per_lane, "lanes_defaulted_roads": self.lanes_defaulted,
                "default_lanes": self.cfg.default_lanes, "exposure": "class_sensitivity x free-flow s / ref",
                "lambda": self.cfg.lam}


def delta_phi(cells: dict, base, coef, extra: dict | None = None) -> float:
    s = 0.0
    for c, w in cells.items():
        L = base(c) + (extra.get(c, 0.0) if extra else 0.0)
        s += coef(c) * ((L + w) ** 2 - L ** 2)
    return s


def joint_penalty(chosen_cells: list[dict], base, coef) -> float:
    """Phi(L_fixed + sum of chosen contributions) - Phi(L_fixed), exactly."""
    tot: dict = {}
    for cs in chosen_cells:
        for c, w in cs.items():
            tot[c] = tot.get(c, 0.0) + w
    return sum(coef(c) * ((base(c) + x) ** 2 - base(c) ** 2) for c, x in tot.items())


def tie_key(seed: int, request_id: str, candidate_id: str) -> str:
    return hashlib.sha1(f"{seed}|{request_id}|{candidate_id}".encode()).hexdigest()
