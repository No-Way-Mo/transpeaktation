"""Policy B: per request, minimise ETA + lambda * [Phi(L + route) - Phi(L)] (scoring.py). Requests of one batch are
processed in their recorded arrival order, each seeing earlier choices. lambda = 0 reproduces forecast_only."""
from __future__ import annotations

from ..schemas import SelectionContext, SelectionResult
from .base import Selector, sequential


class Heuristic(Selector):
    name = "heuristic"
    version = "heuristic-v1"

    def select(self, ctx: SelectionContext) -> SelectionResult:
        return sequential(ctx, ctx.lam, self.name, self.version)
