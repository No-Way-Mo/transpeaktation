"""Demand inputs for citywide batches: event attendance and trip requests (data generation only).

    python -m eventsim.citywide_demand attendance     # -> prepared/event_attendance_v1.csv for every verified event

Demand model (sampler v3.1):
  * Event demand comes from the event's ATTENDANCE (the API will supply it; until then event_attendance_v1.csv),
    converted to vehicle trips by mode assumptions (drive share, occupancy), capped by the v3 load limits.
  * Everything else is a set of trip REQUESTS: one row per request with a departure time and origin/destination
    coordinates, i.e. what clients send. The simulator snaps each request to the nearest drivable road.
    Until real client requests are recorded, synthetic requests are generated in the same format and saved with
    each run (runs/<run>/requests.parquet), so a real request file can replace them one-for-one.

Request format (parquet/csv):
    request_id, depart_local_s (seconds after local midnight of the run's date) or depart_utc (ISO),
    origin_lon, origin_lat, dest_lon, dest_lat, kind (background | event_arrival | event_departure |
    ridehail_dropoff | ridehail_pickup), event_case (optional), stop_lon/stop_lat + dwell_s (optional, ride-hail)
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .config import SF_TZ
from .geo import LocalProj
from .citywide import ROOT, read, save

ATTENDANCE_PATH = ROOT / "prepared" / "event_attendance_v1.csv"
SNAP_MAX_M = 250.0
REQUEST_COLUMNS = ["request_id", "depart_local_s", "origin_lon", "origin_lat", "dest_lon", "dest_lat", "kind",
                   "event_case", "stop_lon", "stop_lat", "dwell_s"]

# Category rules for events without a published figure: (name pattern, point, low, high). Estimates, flagged.
CATEGORY_RULES = [
    (r"block part(y|ies)", 300, 100, 800),
    (r"preschool|nursery|school|church|parish|anniversar", 500, 200, 1_500),
    (r"trick.?or.?treat|treat or treat|halloween", 3_000, 1_000, 10_000),
    (r"night market", 10_000, 5_000, 15_000),
    (r"farmers'? market|market", 2_000, 500, 5_000),
    (r"sunday streets", 15_000, 5_000, 25_000),
    (r"triathlon|marathon|race|\brun\b|walk", 5_000, 2_000, 10_000),
    (r"parade", 20_000, 5_000, 50_000),
    (r"street fair|festival|fest\b|fair\b|street party|celebration", None, 2_000, 50_000),  # scaled by footprint
]


def category_estimate(name: str, segments: int) -> tuple[int, int, int, str]:
    n = name.lower()
    for pat, point, lo, hi in CATEGORY_RULES:
        if re.search(pat, n):
            if point is None:  # size a street fair by its closed footprint (~500 people per closed segment)
                point = int(np.clip(500 * segments, lo, hi))
            return point, lo, hi, f"category rule '{pat}'"
    point = int(np.clip(500 * segments, 300, 10_000))
    return point, 300, 10_000, "default rule: 500 per closed segment"


def build_attendance() -> dict:
    """Attendance for every verified event case: the published figure where one exists (sampler v3 table),
    otherwise a category estimate. This table is the interface the API will feed later."""
    from . import citywide_batch as cb
    review = read(cb.latest_review())
    pool_by_case = {v["case_num"]: (k, v) for k, v in cb.EVENT_POOL_V3.items()}
    rows = []
    for c in review["cases"]:
        if c["status"] != "verified":
            continue
        if c["case_num"] in pool_by_case:
            key, ev = pool_by_case[c["case_num"]]
            lo, hi = ev["attendance"]
            point = ev["attendance_claim"] or int((lo + hi) / 2)
            rows.append({"case_num": c["case_num"], "name": c["name"], "attendance": int(point), "low": lo, "high": hi,
                         "is_estimate": ev["attendance_claim"] is None,
                         "method": "published figure" if ev["attendance_claim"] else "assumed range midpoint",
                         "source": ev["attendance_source"], "event_key": key})
        else:
            point, lo, hi, how = category_estimate(c["name"], c["segments"])
            rows.append({"case_num": c["case_num"], "name": c["name"], "attendance": point, "low": lo, "high": hi,
                         "is_estimate": True, "method": how, "source": "estimate (no published figure looked up)",
                         "event_key": None})
    df = pd.DataFrame(rows).sort_values("attendance", ascending=False)
    df.to_csv(ATTENDANCE_PATH, index=False)
    return {"events": len(df), "published": int((~df.is_estimate).sum()), "estimated": int(df.is_estimate.sum()),
            "path": str(ATTENDANCE_PATH)}


def attendance_for(case_num: str) -> dict:
    """Attendance record for one event (the API will provide this; the CSV is the stand-in)."""
    if not ATTENDANCE_PATH.exists():
        build_attendance()
    df = pd.read_csv(ATTENDANCE_PATH, dtype={"case_num": str})
    row = df[df.case_num == str(case_num)]
    if row.empty:
        raise KeyError(f"no attendance for case {case_num}: run `python -m eventsim.citywide_demand attendance`")
    return row.iloc[0].to_dict()


# ---------------------------------------------------------------- requests

class EdgeSnapper:
    """Nearest routable road for a coordinate (KD-tree over points sampled along each edge)."""

    def __init__(self, patch: dict, ids: list[str]):
        from scipy.spatial import cKDTree
        from .geo import sample_polyline
        self.proj = LocalProj(**patch["proj"])
        pts, owner = [], []
        for i, s in enumerate(ids):
            p, _ = sample_polyline(self.proj.fwd(patch["segments"][s]["coords"]), 25.0)
            pts.append(p)
            owner += [i] * len(p)
        self.ids = ids
        self.owner = np.asarray(owner)
        self.tree = cKDTree(np.vstack(pts))

    def snap(self, lon, lat) -> tuple[np.ndarray, np.ndarray]:
        xy = self.proj.fwd(np.column_stack([lon, lat]))
        d, j = self.tree.query(xy)
        return np.asarray(self.ids, dtype=object)[self.owner[j]], d


def edge_points(patch: dict, ids: list[str], rng, idx: np.ndarray) -> np.ndarray:
    """A random point (lon, lat) on each chosen edge (so synthetic requests look like real coordinates)."""
    out = np.empty((len(idx), 2))
    for k, i in enumerate(idx):
        c = np.asarray(patch["segments"][ids[i]]["coords"])
        a = rng.integers(len(c) - 1) if len(c) > 1 else 0
        t = rng.random()
        out[k] = c[a] + (c[min(a + 1, len(c) - 1)] - c[a]) * t
    return out


def synthetic_requests(patch: dict, fam: dict, run: dict, ids: list[str], weights: np.ndarray,
                       cell_of: list, cells: dict, profile: list[float]) -> pd.DataFrame:
    """Background client requests (stand-in until real ones are recorded): same RNG stream for an event run and
    its control, so the pair's background requests are identical."""
    bg, t = fam["background"], fam["time"]
    rng = np.random.default_rng(run["seed"])
    rows = []
    for h0 in range(t["sim_begin_s"] // 3600 * 3600, t["depart_end_s"], 3600):
        a, b = max(h0, t["sim_begin_s"]), min(h0 + 3600, t["depart_end_s"])
        if b <= a:
            continue
        n = rng.poisson(bg["vph_peak"] * profile[(h0 // 3600) % 24] * bg["profile_jitter"] * (b - a) / 3600)
        o = rng.choice(len(ids), size=n, p=weights)
        deps = np.sort(rng.uniform(a, b, n))
        d = np.array([int(rng.choice(cells[cell_of[x]])) if rng.random() < bg["local_share"] and len(cells[cell_of[x]]) > 1
                      else int(rng.choice(len(ids), p=weights)) for x in o], dtype=int)
        d = np.where(d == o, (d + 1) % len(ids), d)
        op, dp = edge_points(patch, ids, rng, o), edge_points(patch, ids, rng, d)
        for k in range(n):
            rows.append((f"bg{len(rows)}", float(deps[k]), op[k, 0], op[k, 1], dp[k, 0], dp[k, 1], "background",
                         None, np.nan, np.nan, np.nan))
    return pd.DataFrame(rows, columns=REQUEST_COLUMNS)


def load_requests(path, fam: dict) -> pd.DataFrame:
    """Real client requests for a run's window (depart_utc or depart_local_s)."""
    df = pd.read_parquet(path) if str(path).endswith(".parquet") else pd.read_csv(path)
    if "depart_local_s" not in df and "depart_utc" in df:
        midnight = datetime.fromisoformat(fam["date"]).replace(tzinfo=SF_TZ)
        df["depart_local_s"] = [(pd.Timestamp(x).tz_convert(SF_TZ) - midnight).total_seconds() for x in df.depart_utc]
    t = fam["time"]
    df = df[(df.depart_local_s >= t["sim_begin_s"]) & (df.depart_local_s < t["depart_end_s"])].copy()
    for c in REQUEST_COLUMNS:
        if c not in df:
            df[c] = np.nan if c not in ("kind",) else "background"
    return df[REQUEST_COLUMNS]


def trips_from_requests(req: pd.DataFrame, snapper: EdgeSnapper) -> tuple[list[dict], dict]:
    """Snap requests to roads -> SUMO trips. Requests farther than SNAP_MAX_M from any routable road are dropped
    and counted (never silently moved across the city)."""
    o, do = snapper.snap(req.origin_lon.to_numpy(), req.origin_lat.to_numpy())
    d, dd = snapper.snap(req.dest_lon.to_numpy(), req.dest_lat.to_numpy())
    has_stop = req.stop_lon.notna().to_numpy()
    st = np.full(len(req), None, dtype=object)
    ds = np.zeros(len(req))
    if has_stop.any():
        st[has_stop], ds[has_stop] = snapper.snap(req.stop_lon[has_stop].to_numpy(), req.stop_lat[has_stop].to_numpy())
    ok = (do <= SNAP_MAX_M) & (dd <= SNAP_MAX_M) & (o != d) & (~has_stop | (ds <= SNAP_MAX_M))
    trips = []
    for i in np.flatnonzero(ok):
        r = req.iloc[i]
        tr = {"id": str(r.request_id), "kind": str(r.kind), "depart": float(r.depart_local_s), "from": o[i], "to": d[i]}
        if has_stop[i] and st[i] not in (o[i], d[i]):
            tr.update(stop=st[i], dwell=float(r.dwell_s), off_lane=True)
        trips.append(tr)
    trips.sort(key=lambda x: x["depart"])
    stats = {"requests": int(len(req)), "trips": len(trips), "dropped_far_from_road": int((~((do <= SNAP_MAX_M) & (dd <= SNAP_MAX_M))).sum()),
             "dropped_same_origin_destination": int(((o == d) & (do <= SNAP_MAX_M) & (dd <= SNAP_MAX_M)).sum()),
             "snap_distance_m_p95": float(np.percentile(np.r_[do, dd], 95)) if len(req) else 0.0}
    return trips, stats


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("stage", choices=["attendance"])
    a = p.parse_args()
    print(json.dumps(build_attendance(), indent=1))


if __name__ == "__main__":
    main()
