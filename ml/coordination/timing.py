"""Advance the forecast clock over a fixed road sequence.

* The vehicle starts ON the origin road at `depart` at fraction f0, so a closure on the origin road does not trap
  it (being on a road and entering a closed road are different cases). If the origin road has no usable forecast
  for that interval its remaining part is priced at free flow and flagged `origin_cost_free_flow`.
* Every later road is ENTERED at the time the previous one is left; that entry time picks the forecast interval.
  Entry is refused if the interval is not enterable, or if a full (clearance) closure overlaps [entry, exit).
  Partial/lane restrictions do not block and are flagged.
* An entry or arrival beyond the last forecast interval is refused (`beyond_horizon`): the last bucket is never
  silently extended.
* Only forecast travel time advances the clock. Nothing here knows about allocation pressure.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np

from .forecast_store import ForecastSnapshot
from .network import RoadNetwork
from .schemas import RoadEntry, TimedRoute


class Infeasible(Exception):
    def __init__(self, reason: str, road: int | None = None, at: float | None = None):
        super().__init__(reason)
        self.reason, self.road, self.at = reason, road, at


def evaluate(net: RoadNetwork, snap: ForecastSnapshot, roads: list, f0: float, g1: float, depart: float,
             check_arcs: bool = True) -> TimedRoute:
    if not roads:
        raise Infeasible("empty_route")
    if len(roads) == 1 and g1 < f0:
        raise Infeasible("same_road_behind_origin", roads[0])
    t = depart
    flags: set[str] = set()
    entries = []
    dist = 0.0
    expo: dict[str, float] = defaultdict(float)
    last = len(roads) - 1
    for n, i in enumerate(roads):
        if n > 0 and check_arcs and not net.has_arc(roads[n - 1], i):
            raise Infeasible("illegal_connection", i, t)
        k = snap.bucket(t)
        if k < 0:
            raise Infeasible("before_issue_time", i, t)
        if k >= snap.H:
            raise Infeasible("beyond_horizon", i, t)
        a = f0 if n == 0 else 0.0
        b = g1 if n == last else 1.0
        share = max(b - a, 0.0)
        if snap.ok[i, k]:
            tt = float(snap.tt[i, k])
        elif n == 0:
            tt = float(net.ff_tt_s[i])
            flags.add("origin_cost_free_flow")
        else:
            raise Infeasible("not_enterable", i, t)
        dt = tt * share
        if n > 0:
            if snap.blocked(i, t, t + dt) is not None:
                raise Infeasible("closure", i, t)
            if any(kind in ("partial", "lane") and b0 < t + dt and t < e0 for b0, e0, kind in snap.closures.get(i, ())):
                flags.add("partial_restriction_on_route")
        if snap.source[i, k] == "representative_road":
            flags.add("representative_road")
        entries.append(RoadEntry(int(i), t, t + dt, a, b))
        dist += net.length_m[i] * share
        expo[net.hw[i]] += dt
        t += dt
    if t > snap.horizon_end:
        raise Infeasible("beyond_horizon", roads[-1], t)
    return TimedRoute(roads=[int(r) for r in roads], entries=entries, depart=depart, arrive=t, distance_m=float(dist),
                      flags=sorted(flags), class_exposure_s=dict(expo))


def overlap_share(a: TimedRoute, b: TimedRoute) -> float:
    """Share of a's forecast travel time spent on roads that b also uses."""
    rb = set(b.roads)
    tot = sum(e.exit - e.entry for e in a.entries)
    if tot <= 0:
        return 1.0 if rb & set(a.roads) else 0.0
    return float(sum(e.exit - e.entry for e in a.entries if e.road in rb) / tot)


def cells(net: RoadNetwork, entries, bin_s: float, spread: list) -> dict:
    """Participating road entries per (allocation resource, time bin). Each entry weighs 1 in total; an optional
    centred kernel spreads it over adjacent bins (weights sum to 1). Identical for every selector."""
    out: dict[tuple, float] = defaultdict(float)
    ker = np.asarray(spread, float)
    ker = ker / ker.sum()
    half = len(ker) // 2
    for e in entries:
        r = int(net.resource[e.road])
        b = int(e.entry // bin_s)
        for j, w in enumerate(ker):
            if w > 0:
                out[(r, b + j - half)] += float(w)
    return dict(out)
