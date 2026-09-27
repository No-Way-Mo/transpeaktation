"""Policy A: minimum forecast ETA among feasible candidates. Ignores allocation pressure when choosing; its route is
still recorded in the ledger so its concentration can be measured."""
from __future__ import annotations

from ..schemas import SelectionContext, SelectionResult
from .base import Selector, sequential


class ForecastOnly(Selector):
    name = "forecast_only"
    version = "forecast_only-v1"

    def select(self, ctx: SelectionContext) -> SelectionResult:
        return sequential(ctx, 0.0, self.name, self.version)
