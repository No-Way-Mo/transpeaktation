"""Selector interface. Selectors only PROPOSE one candidate index per request; the coordinator validates and commits.
Every selector sees the same SelectionContext (same candidates, masks, fixed existing load, versions, seed)."""
from __future__ import annotations

import time
from abc import ABC, abstractmethod

from ..schemas import SelectionContext, SelectionResult
from ..scoring import delta_phi, joint_penalty, tie_key


class SelectorUnavailable(Exception):
    """The policy cannot run (e.g. no trained checkpoint). The coordinator falls back and records why."""


class Selector(ABC):
    name = "base"
    version = "0"

    @abstractmethod
    def select(self, ctx: SelectionContext) -> SelectionResult: ...


def valid_indices(item) -> list[int]:
    return [k for k, ok in enumerate(item.mask) if ok]


def pick_min(ctx: SelectionContext, item, scores: dict[int, float]) -> tuple[int, bool]:
    """Minimum score; candidates within tie_s of it are broken by a seeded hash (reproducible, order-free).
    Returns (index, was_tie)."""
    best = min(scores.values())
    near = [k for k, s in scores.items() if s <= best + ctx.tie_s]
    if len(near) == 1:
        return near[0], False
    rid = item.request.request_id
    return min(near, key=lambda k: tie_key(ctx.seed, rid, item.candidates[k].candidate_id)), True


def exact_joint_score(ctx: SelectionContext, choices: dict) -> dict:
    """ETA sum and lambda-weighted joint penalty of a full assignment, in the shared exact scoring."""
    eta = 0.0
    chosen_cells = []
    for item in ctx.items:
        k = choices.get(item.request.request_id)
        if k is None:
            continue
        c = item.candidates[k]
        eta += c.eta_s
        chosen_cells.append(c.cells)
    pen = joint_penalty(chosen_cells, ctx.base_load, ctx.cell_coef)
    return {"eta_s": eta, "penalty": pen, "score": eta + ctx.lam * pen}


def sequential(ctx: SelectionContext, lam: float, name: str, version: str) -> SelectionResult:
    """Process requests in arrival order; each sees the fixed load plus earlier choices in this batch."""
    t0 = time.perf_counter()
    extra: dict = {}
    res = SelectionResult(choices={}, policy=name, policy_version=version)
    for item in ctx.items:
        rid = item.request.request_id
        idx = valid_indices(item)
        if not idx:
            res.reasons[rid] = ["no_valid_candidate"]
            continue
        diag, scores = {}, {}
        for k in idx:
            c = item.candidates[k]
            pen = delta_phi(c.cells, ctx.base_load, ctx.cell_coef, extra) if lam else 0.0
            scores[k] = c.eta_s + lam * pen
            diag[c.candidate_id] = {"eta_s": round(c.eta_s, 2), "penalty": round(pen, 6),
                                    "selection_score": round(scores[k], 3)}
        k, tie = pick_min(ctx, item, scores)
        res.choices[rid] = k
        res.diagnostics[rid] = diag
        fastest = min(idx, key=lambda j: (item.candidates[j].eta_s, item.candidates[j].candidate_id))
        why = ["fastest_candidate"] if k == fastest else ["lower_concentration_within_detour_bound"]
        if tie:
            why.append("seeded_tie_break")
        res.reasons[rid] = why
        for c, w in item.candidates[k].cells.items():
            extra[c] = extra.get(c, 0.0) + w
    res.runtime_ms = (time.perf_counter() - t0) * 1000
    return res
