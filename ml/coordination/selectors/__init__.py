from .base import Selector, SelectorUnavailable
from .batch import Batch
from .forecast_only import ForecastOnly
from .heuristic import Heuristic
from .rl import RL

NAMES = ("forecast_only", "heuristic", "batch", "rl")


def make(name: str, cfg) -> Selector:
    if name == "forecast_only":
        return ForecastOnly()
    if name == "heuristic":
        return Heuristic()
    if name == "batch":
        return Batch(cfg.batch)
    if name == "rl":
        return RL(cfg)
    raise ValueError(f"unknown selector {name!r}; choose from {NAMES}")
