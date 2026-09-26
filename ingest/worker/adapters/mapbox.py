"""Mapbox corridor polls (`python -m pull.poll`, data/timeseries/mapbox_corridors/*.jsonl)
-> one traffic_metric per OSM edge per poll, for Tiger `traffic_metrics`.

Mapbox annotates each piece between consecutive route coordinates. A piece belongs to the
directed OSM edge whose nearest part is within MATCH_M of the piece midpoint and runs the
same way (heading within MAX_ANGLE). Pieces on the same edge are summed; the edge is kept
only if they cover >= MIN_COVERAGE of its length, so ends of a route don't produce
half-edge readings.

Contract columns filled: time, road_segment_id, source, speed_mph, travel_time_sec.
free_flow_speed_mph / congestion_ratio stay NULL: Mapbox's congestion_numeric (0-100) is
not the contract's `1 - speed/free_flow` (see TODO.md).
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..context import Context
from ..geo import angle_diff, bearing_deg, line_length_m, valid_lonlat
from ..records import Record, RecordError
from ..timeutil import iso

SOURCE = "mapbox_corridors"
TIGER_SOURCE = "mapbox"          # traffic_metrics.source value
MATCH_M = 12.0
MAX_ANGLE = 45.0
MIN_COVERAGE = 0.5
MPS_TO_MPH = 2.2369362920544


def _time(v) -> datetime:
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        raise RecordError(f"bad polled_at {v!r}")
    if dt.tzinfo is None:
        raise RecordError(f"polled_at without zone {v!r}")
    return dt.astimezone(timezone.utc)


def mapbox_corridors(row: dict, ctx: Context) -> list[Record] | None:
    if not row.get("ok"):
        return None  # failed request; pull.poll logged the error in the row
    t = _time(row.get("polled_at"))
    seg, coords = row.get("segments") or {}, row.get("geometry") or []
    dist, dur = seg.get("distance_m") or [], seg.get("duration_s") or []
    n = len(dist)
    if not n or len(dur) != n or len(coords) != n + 1:
        raise RecordError(f"segment arrays disagree: {n} distances, {len(dur)} durations, {len(coords)} coords")
    cong = seg.get("congestion_numeric") or [None] * n

    agg: dict[str, list[float]] = {}  # segment_id -> [metres, seconds, congestion*metres, congestion metres]
    for i in range(n):
        a, b, d, s = coords[i], coords[i + 1], dist[i], dur[i]
        if not (valid_lonlat(*a[:2]) and valid_lonlat(*b[:2])):
            raise RecordError(f"invalid coordinate at piece {i}")
        if not d or not s or d <= 0 or s <= 0:
            continue
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        heading = bearing_deg(tuple(a[:2]), tuple(b[:2]))
        hit = next((k for _, k, brg in ctx.osm.near(mid, MATCH_M) if angle_diff(heading, brg) <= MAX_ANGLE), None)
        if hit is None:
            continue
        acc = agg.setdefault(hit, [0.0, 0.0, 0.0, 0.0])
        acc[0] += d
        acc[1] += s
        if i < len(cong) and cong[i] is not None:
            acc[2] += cong[i] * d
            acc[3] += d

    out = []
    for sid in sorted(agg):
        metres, secs, cong_m, cong_n = agg[sid]
        length = line_length_m(ctx.osm.geometry[sid])
        if length <= 0 or metres < MIN_COVERAGE * length:
            continue
        mps = metres / secs
        out.append(Record(
            kind="traffic_metric", source=SOURCE, source_id=f"{iso(t)}|{sid}", observed_at=t,
            road_segment_ids=[sid], location_status="network_ref",
            attributes={
                "road_segment_id": sid,
                "tiger_source": TIGER_SOURCE,
                "speed_mph": round(mps * MPS_TO_MPH, 2),
                "travel_time_sec": round(length / mps, 1),  # full edge at the observed speed
                "free_flow_speed_mph": None,
                "congestion_ratio": None,
                # debugging context (not a Tiger column)
                "corridor": row.get("corridor"),
                "direction": row.get("direction"),
                "covered_m": round(metres, 1),
                "edge_length_m": round(length, 1),
                "mapbox_congestion_numeric": round(cong_m / cong_n, 1) if cong_n else None,
            },
        ))
    return out


NORMALIZERS = {SOURCE: mapbox_corridors}
REQUIRES_OSM = {SOURCE: "needs the OSM drive graph (python -m pull osm_drive_graph) to map Mapbox pieces "
                        "onto traffic_metrics.road_segment_id; polls left in data/timeseries/"}
