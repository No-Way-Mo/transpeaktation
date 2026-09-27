"""Local adapter: forecast export + closure intervals + legal road connections -> time-dependent travel costs.

    router = ForecastRouter.from_files("forecast.parquet", "data/sf_citywide/net_v3/arcs_c90.json")
    router.route(vehicle_road, pickup_road, depart_at)        # vehicle -> pickup
    router.many_to_one([v1, v2, ...], pickup_road, depart_at) # candidate vehicles for one request
    router.route(pickup_road, dropoff_road, pickup_time)      # trip

Semantics
* A route starts when the vehicle enters `origin` at `depart_at` and ends when it leaves `destination`.
* The cost of a road is the forecast for the bucket in which the vehicle ENTERS it (FIFO time-dependent Dijkstra).
* A road cannot be entered while a known closure interval covers the entry time (exact timestamps from the closures
  table, never smoothed into congestion), nor when its availability for that bucket is closed / unavailable, nor
  when passenger access is barred.
* Entry after the last forecast bucket uses the last horizon's value and the result is flagged `beyond_horizon`.
  Entry before issued_at is refused.
This is only a travel-time oracle for the fleet optimizer; requests, fleet positions, capacity and battery are its
own inputs. Nothing here derives passenger demand from congestion.
"""
from __future__ import annotations

import heapq
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass
class RouteResult:
    reachable: bool
    depart_at: pd.Timestamp
    arrive_at: pd.Timestamp | None = None
    travel_time_sec: float | None = None
    path: list[str] = field(default_factory=list)
    beyond_horizon: bool = False
    sources: dict = field(default_factory=dict)


class ForecastRouter:
    def __init__(self, forecast: pd.DataFrame, closures: pd.DataFrame, arcs: list[tuple[str, str]]):
        f = forecast.sort_values(["road_segment_id", "horizon_min"])
        self.issued_at = pd.Timestamp(f.issued_at.iloc[0]).timestamp()
        self.bucket_s = float((pd.Timestamp(f.valid_to.iloc[0]) - pd.Timestamp(f.valid_from.iloc[0])).total_seconds())
        self.H = int(f.horizon_min.nunique())
        ids = f.road_segment_id.unique()
        self.pos = {s: i for i, s in enumerate(ids)}
        self.ids = ids
        self.tt = f.predicted_travel_time_sec.to_numpy(float).reshape(len(ids), self.H)
        avail = f.availability.to_numpy().reshape(len(ids), self.H)
        reason = f.restriction_reason.to_numpy().reshape(len(ids), self.H)
        self.src = f.prediction_source.to_numpy().reshape(len(ids), self.H)
        # a bucket is enterable if open, or restricted only by a partial closure (the exact interval decides)
        self.ok = (avail == "open") | ((avail == "restricted") & (reason == "partial_closure_see_closures_table"))
        self.ok &= np.isfinite(self.tt)
        self.closures: dict[str, list[tuple[float, float]]] = {}
        for r in closures.itertuples():
            if r.restriction == "full":
                self.closures.setdefault(r.road_segment_id, []).append(
                    (pd.Timestamp(r.closure_begin).timestamp(), pd.Timestamp(r.closure_end).timestamp()))
        self.succ: dict[int, list[int]] = {}
        for a, b in arcs:
            if a in self.pos and b in self.pos:
                self.succ.setdefault(self.pos[a], []).append(self.pos[b])

    @classmethod
    def from_files(cls, forecast_path, arcs_path) -> "ForecastRouter":
        fp = Path(forecast_path)
        return cls(pd.read_parquet(fp), pd.read_parquet(fp.with_suffix(".closures.parquet")),
                   [tuple(a) for a in json.loads(Path(arcs_path).read_text())])

    def closed_at(self, road: str, t: float) -> bool:
        return any(b <= t < e for b, e in self.closures.get(road, ()))

    def cost(self, i: int, t: float) -> tuple[float, bool]:
        """(travel time for entering road i at epoch t, beyond_horizon); inf when it cannot be entered."""
        k = int((t - self.issued_at) // self.bucket_s)
        if k < 0:
            raise ValueError("entry before the forecast issue time")
        beyond = k >= self.H
        k = min(k, self.H - 1)
        if not self.ok[i, k] or self.closed_at(self.ids[i], t):
            return float("inf"), beyond
        return float(self.tt[i, k]), beyond

    def route(self, origin: str, destination: str, depart_at) -> RouteResult:
        t0 = pd.Timestamp(depart_at).timestamp()
        res = RouteResult(False, pd.Timestamp(depart_at, unit="s", tz="UTC") if not isinstance(depart_at, pd.Timestamp)
                          else depart_at)
        if origin not in self.pos or destination not in self.pos:
            return res
        o, d = self.pos[origin], self.pos[destination]
        c, beyond = self.cost(o, t0)
        if not np.isfinite(c):
            return res
        best = {o: t0 + c}
        enter = {o: t0}
        prev = {o: -1}
        flag = {o: beyond}
        heap = [(t0 + c, o)]
        while heap:
            t, i = heapq.heappop(heap)
            if t > best.get(i, np.inf):
                continue
            if i == d:
                path = []
                j = i
                while j != -1:
                    path.append(self.ids[j]); j = prev[j]
                path.reverse()
                ks = [min(self.H - 1, int((enter[self.pos[p]] - self.issued_at) // self.bucket_s)) for p in path]
                srcs = pd.Series([self.src[self.pos[p], k] for p, k in zip(path, ks)]).value_counts()
                return RouteResult(True, res.depart_at, pd.Timestamp(t, unit="s", tz="UTC"), t - t0, path,
                                   flag[i], srcs.to_dict())
            for j in self.succ.get(i, ()):
                cj, bj = self.cost(j, t)
                tj = t + cj
                if tj < best.get(j, np.inf):
                    best[j], enter[j], prev[j], flag[j] = tj, t, i, flag[i] or bj
                    heapq.heappush(heap, (tj, j))
        return res

    def many_to_one(self, vehicle_roads: list[str], pickup_road: str, depart_at) -> pd.DataFrame:
        rows = []
        for v in vehicle_roads:
            r = self.route(v, pickup_road, depart_at)
            rows.append({"vehicle_road": v, "reachable": r.reachable, "eta_sec": r.travel_time_sec,
                         "arrive_at": r.arrive_at, "segments": len(r.path), "beyond_horizon": r.beyond_horizon})
        return pd.DataFrame(rows).sort_values("eta_sec", na_position="last").reset_index(drop=True)
