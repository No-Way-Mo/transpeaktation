"""Realized vehicle-time accounting.

In-scope population P (fixed per scenario, independent of the policy): every vehicle whose scheduled departure is
before the end of the decision window. Per simulation step each P-vehicle that is running (including teleporting)
or waiting for insertion after its scheduled departure adds dt vehicle-seconds. Scoring starts at the first
decision time; vehicles already present then contribute their remaining time.

reward(step) = -(vehicle-seconds accrued since the previous decision) / reward_scale_s (fixed).
The episode ends when every P-vehicle has arrived (terminated) or at the drain cap (truncated). At a cap the
unfinished vehicles are counted and a separately labeled lower-bound estimate of their censored time is
reported; it is NOT added to the reward and never presented as measured travel time.
"""
from __future__ import annotations


class VehicleTime:
    def __init__(self, in_scope: set, scale: float):
        self.P = set(in_scope)
        self.scale = scale
        self.remaining = set(in_scope)       # not yet arrived
        self.running: set = set()
        self.total_s = 0.0
        self._since = 0.0
        self.scoring = False

    def start_scoring(self, running_ids, pending_ids, depart_of: dict, now_local: float) -> None:
        """Scoring starts at the first decision: P-vehicles still running, waiting, or not yet due. Identical whether
        the history period was simulated or loaded from a verified state."""
        running = {v for v in running_ids if v in self.P}
        pending = {v for v in pending_ids if v in self.P}
        future = {v for v in self.P if depart_of.get(v, -1) >= now_local}
        self.running = running
        self.remaining = running | pending | future
        self.scoring = True

    def departed(self, ids) -> None:
        self.running.update(i for i in ids if i in self.P)

    def arrived(self, ids) -> None:
        for i in ids:
            self.running.discard(i)
            self.remaining.discard(i)

    def accrue(self, pending_ids, dt: float) -> None:
        if not self.scoring:
            return
        n = len(self.running) + sum(1 for v in pending_ids if v in self.P)
        self.total_s += n * dt
        self._since += n * dt

    def take_reward(self) -> float:
        r = -self._since / self.scale
        self._since = 0.0
        return r

    def done(self) -> bool:
        return not self.remaining

    def censored(self, now_local: float, depart_of: dict) -> dict:
        """At a drain cap: unfinished P-vehicles and a lower bound of their already-elapsed-but-unscored time."""
        unfinished = sorted(self.remaining)
        return {"unfinished": len(unfinished),
                "unfinished_not_departed_yet": sum(1 for v in unfinished if depart_of.get(v, 0) > now_local),
                "censored_note": "time after the drain cap is unobserved; not added to reward"}


class CongestionExposure:
    """Observed congestion exposure (benchmark outcome, never part of the reward).

    From the scoring start, every simulation step adds dt to
    * observed_s:   vehicles on a mapped road (internal junction edges and unmapped roads are not observed),
    * congested_s:  ... of which at speed <= `ratio` x the road's free-flow speed (congestion_ratio >= 1 - ratio,
                    the same free-flow reference the forecaster uses),
    * stopped_s:    ... of which at speed < `stop_mps` (queued),
    split into all vehicles (`*_all`) and the in-scope population P (`*_scope`); and
    * pending_s_scope: in-scope vehicles waiting off-network for insertion (an off-road queue, not a road queue).
    Per-road congested/observed vehicle-seconds (all vehicles) and an `every_s` time series are kept for maps and
    congestion-evolution plots.
    """
    KEYS = ("observed_s_all", "congested_s_all", "stopped_s_all", "observed_s_scope", "congested_s_scope",
            "stopped_s_scope", "pending_s_scope")

    def __init__(self, free_flow_mps, in_scope: set, ratio: float = 0.5, stop_mps: float = 0.1,
                 every_s: float = 300.0):
        import numpy as np
        self.np = np
        self.thr = ratio * np.asarray(free_flow_mps, float)
        self.P = in_scope
        self.ratio, self.stop_mps, self.every_s = ratio, stop_mps, every_s
        self.road_congested_s = np.zeros(len(self.thr))
        self.road_observed_s = np.zeros(len(self.thr))
        self.tot = dict.fromkeys(self.KEYS, 0.0)
        self._win = dict.fromkeys(self.KEYS, 0.0)
        self._win_arrived = 0
        self._win_start = None
        self.series: list = []
        self.scoring = False

    def start(self, now_local: float) -> None:
        self.scoring = True
        self._win_start = now_local

    def sample(self, roads, speeds, in_scope_mask, n_pending_scope: int, n_arrived_scope: int, dt: float,
               t_after: float) -> None:
        """roads/speeds/in_scope_mask: vehicles on mapped roads this step; t_after = simulation time after it."""
        if not self.scoring:
            return
        np = self.np
        cong = speeds <= self.thr[roads] if len(roads) else np.zeros(0, bool)
        stop = speeds < self.stop_mps if len(roads) else np.zeros(0, bool)
        sc = in_scope_mask
        add = {"observed_s_all": len(roads), "congested_s_all": int(cong.sum()), "stopped_s_all": int(stop.sum()),
               "observed_s_scope": int(sc.sum()), "congested_s_scope": int((cong & sc).sum()),
               "stopped_s_scope": int((stop & sc).sum()), "pending_s_scope": n_pending_scope}
        for k, n in add.items():
            self.tot[k] += n * dt
            self._win[k] += n * dt
        self._win_arrived += n_arrived_scope
        if len(roads):
            np.add.at(self.road_observed_s, roads, dt)
            if cong.any():
                np.add.at(self.road_congested_s, roads[cong], dt)
        if t_after - self._win_start >= self.every_s - 1e-9:
            self.flush(t_after)

    def flush(self, t_after: float) -> None:
        if self._win_start is None or t_after <= self._win_start:
            return
        span = t_after - self._win_start
        self.series.append({"t0": self._win_start, "t1": t_after, "arrived_scope": self._win_arrived,
                            **{f"{k}_mean_vehicles": v / span for k, v in self._win.items()}})
        self._win = dict.fromkeys(self.KEYS, 0.0)
        self._win_arrived = 0
        self._win_start = t_after

    def summary(self) -> dict:
        h = {k.replace("_s_", "_h_"): v / 3600.0 for k, v in self.tot.items()}
        return {**h, "definition": f"vehicle-hours from the scoring start on mapped roads; congested = speed <= "
                                   f"{self.ratio:g} x free-flow; stopped = speed < {self.stop_mps:g} m/s; pending = "
                                   f"in-scope vehicles waiting for insertion (off-network)"}
