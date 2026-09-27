"""The one authoritative allocation ledger (in memory; persisted by storage.py; mutated only by the coordinator).

L[resource, bin] = expected participating road entries from live assignments (provisional, accepted, active), over
the REMAINING schedule of each. This is allocation pressure among participants, not observed road volume, and it is
never added to background traffic already represented in the forecast.
"""
from __future__ import annotations

from collections import defaultdict

from .config import LedgerCfg
from .network import RoadNetwork
from .schemas import LIVE, Assignment, RoadEntry
from .timing import cells


def schedule_entries(net: RoadNetwork, a: Assignment, from_idx: int | None = None) -> list[RoadEntry]:
    i0 = a.progress_idx if from_idx is None else from_idx
    return [RoadEntry(net.pos[r], en, ex, f0, f1) for r, en, ex, f0, f1 in a.schedule[i0:]]


class Ledger:
    def __init__(self, net: RoadNetwork, cfg: LedgerCfg):
        self.net, self.cfg = net, cfg
        self.bin_s = cfg.bin_min * 60.0
        self.assignments: dict[str, Assignment] = {}
        self.by_request: dict[str, str] = {}
        self.load: dict[tuple, float] = defaultdict(float)
        self._contrib: dict[str, dict] = {}
        self.version = 0

    def cells_of_entries(self, entries) -> dict:
        return cells(self.net, entries, self.bin_s, self.cfg.spread)

    def contribution(self, a: Assignment) -> dict:
        return self.cells_of_entries(schedule_entries(self.net, a)) if a.status in LIVE else {}

    def get(self, cell) -> float:
        return self.load.get(cell, 0.0)

    def getter(self, exclude: str | None = None):
        """Read-only view of existing load, optionally without one assignment's own contribution (reroutes)."""
        if exclude is None or exclude not in self._contrib:
            return self.get
        own = self._contrib[exclude]
        return lambda c: max(self.load.get(c, 0.0) - own.get(c, 0.0), 0.0)

    def apply(self, updated: list[Assignment]) -> None:
        """Replace/insert assignments and their load contributions as one step (the caller holds the lock and has
        already persisted them)."""
        for a in updated:
            old = self._contrib.pop(a.assignment_id, None)
            if old:
                for c, w in old.items():
                    v = self.load[c] - w
                    if v > 1e-9:
                        self.load[c] = v
                    else:
                        self.load.pop(c, None)
            self.assignments[a.assignment_id] = a
            self.by_request[a.request_id] = a.assignment_id
            new = self.contribution(a)
            if new:
                self._contrib[a.assignment_id] = new
                for c, w in new.items():
                    self.load[c] += w
        self.version += 1

    def forget_terminal(self) -> None:
        """Drop finished assignments from memory (they stay in SQLite for idempotent lookups)."""
        for k in [k for k, a in self.assignments.items() if a.status not in LIVE]:
            a = self.assignments.pop(k)
            self.by_request.pop(a.request_id, None)

    def live(self) -> list[Assignment]:
        return [a for a in self.assignments.values() if a.status in LIVE]

    def total_load(self) -> float:
        return float(sum(self.load.values()))
