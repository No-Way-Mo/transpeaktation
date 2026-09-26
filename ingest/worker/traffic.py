"""Traffic loaders: `python -m pull.poll` JSONL -> Tiger `traffic_metrics` (+ Mapbox route ETAs).

Follows AGENTS.md "Traffic data normalization":
  * every reading is snapped to an OSM segment_id ("u-v-key"); provider geometry stays here
  * one row per segment x 10-min UTC bucket x source; readings averaged within the bucket
  * speed_mph, free_flow_speed_mph, congestion_ratio = clamp(1 - speed/free_flow, 0, 1)
  * sources: tomtom | mapbox_route | mapbox_tiles | muni (muni never averaged into the others)
  * only observed buckets are written; gap filling is ml/'s job

Incremental: each source has a watermark (start of the first bucket not yet written). A run
reads day files from the watermark's date and writes only buckets that closed at least LAG
ago, so a bucket still being polled is never written half-full. Day files are processed one
at a time, so memory stays flat no matter how much history there is.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Protocol

from pull.poll import MAPBOX_TILES_DIR, MUNI_DIR, TOMTOM_DIR, TS_DIR

from .geo import LonLat, haversine_m
from .network import Network
from .state import LineMaps, State

BUCKET = timedelta(minutes=10)
LAG = timedelta(minutes=5)  # tile rounds are stamped at their start and written at their end

MPS_TO_MPH = 2.2369362920544
KMH_TO_MPH = 0.621371192
MAX_MPH = 100.0

# Mapbox traffic-tile congestion -> congestion_ratio, until calibrated per road class against
# segments that also have a measured speed (AGENTS.md).
TILE_CONGESTION_RATIO = {"low": 0.1, "moderate": 0.4, "heavy": 0.65, "severe": 0.85}

MAPBOX_MIN_COVERAGE = 0.5          # a corridor must drive >= half an edge to report its speed
TOMTOM_RELATIVE_MAX_AGE = timedelta(hours=12)  # relative tiles come every 6 h
TOMTOM_MIN_RELATIVE = 0.05         # below this, absolute / relative blows up
MUNI_MAX_GAP_S = 180               # consecutive fixes further apart aren't one movement
MUNI_MAX_HOP_M = 1500              # > ~37 mph over 90 s on city streets: a GPS jump
MUNI_STOPPED_M = 5                 # below this the bus didn't move; use its reported bearing

SOURCES = ("tomtom", "mapbox_route", "mapbox_tiles", "muni")
DIRS = {"tomtom": TOMTOM_DIR, "mapbox_route": TS_DIR, "mapbox_tiles": MAPBOX_TILES_DIR, "muni": MUNI_DIR}


class Sink(Protocol):
    def write_traffic(self, rows: list[dict]) -> None: ...
    def write_route_eta(self, rows: list[dict]) -> None: ...
    def write_route_plans(self, docs: list[dict]) -> None: ...


def bucket_of(t: datetime) -> datetime:
    t = t.astimezone(timezone.utc)
    return t.replace(minute=t.minute - t.minute % 10, second=0, microsecond=0)


def parse_time(v: Any) -> datetime:
    dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"time without zone: {v!r}")
    return dt.astimezone(timezone.utc)


def day_files(directory: Path, since: date | None, until: date) -> list[Path]:
    """Date-named JSONL files (<UTC date>.jsonl) in [since, until]; skips geometry.jsonl etc."""
    out = []
    for p in sorted(directory.glob("*.jsonl")) if directory.is_dir() else []:
        try:
            d = date.fromisoformat(p.stem)
        except ValueError:
            continue
        if (since is None or d >= since) and d <= until:
            out.append(p)
    return out


def read_jsonl(path: Path, stats: Counter) -> Iterator[dict]:
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                stats["bad_lines"] += 1
                continue
            if isinstance(row, dict):
                yield row
            else:
                stats["bad_lines"] += 1


@dataclass
class _Acc:
    speed_w: float = 0.0
    speed_sum: float = 0.0
    ff_w: float = 0.0
    ff_sum: float = 0.0
    ratio_w: float = 0.0
    ratio_sum: float = 0.0

    def speed(self, mph: float, w: float) -> None:
        self.speed_w += w
        self.speed_sum += mph * w

    def free_flow(self, mph: float, w: float) -> None:
        self.ff_w += w
        self.ff_sum += mph * w

    def ratio(self, r: float, w: float) -> None:
        self.ratio_w += w
        self.ratio_sum += r * w


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


@dataclass
class SourceRun:
    """One source's pass over one window: accumulates readings, then emits rows."""

    source: str
    net: Network
    state: State
    start: datetime | None   # first bucket to write (None = from the beginning)
    end: datetime            # first bucket NOT to write (still open)
    acc: dict[tuple[datetime, str], _Acc] = field(default_factory=lambda: defaultdict(_Acc))
    stats: Counter = field(default_factory=Counter)
    eta_rows: list[dict] = field(default_factory=list)
    plans: dict[str, dict] = field(default_factory=dict)

    def in_window(self, t: datetime) -> bool:
        b = bucket_of(t)
        return (self.start is None or b >= self.start) and b < self.end

    def rows(self) -> list[dict]:
        out = []
        tomtom_ff: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
        for (b, sid), a in sorted(self.acc.items()):
            edge = self.net.edges[sid]
            speed = a.speed_sum / a.speed_w if a.speed_w else None
            if self.source == "tomtom" and a.ff_w:
                ff = a.ff_sum / a.ff_w
                tomtom_ff[sid][0] += a.ff_sum
                tomtom_ff[sid][1] += a.ff_w
            else:
                ff = self.state.tomtom_free_flow.get(sid) or edge.free_flow_mph
            if speed is not None and ff:
                ratio = _clamp01(1 - speed / ff)
            else:
                ratio = a.ratio_sum / a.ratio_w if a.ratio_w else None
            travel = (round(edge.length_m / (speed * 0.44704), 1)
                      if speed and self.source in ("tomtom", "mapbox_route") else None)
            out.append({"time": b, "road_segment_id": sid, "source": self.source,
                        "speed_mph": None if speed is None else round(speed, 2),
                        "free_flow_speed_mph": round(ff, 2) if ff else None,
                        "travel_time_sec": travel,
                        "congestion_ratio": None if ratio is None else round(ratio, 4)})
        for sid, (s, w) in tomtom_ff.items():  # latest measured free flow, reused by the other sources
            self.state.tomtom_free_flow[sid] = round(s / w, 2)
        self.acc.clear()
        return out


# --- per-source readers ------------------------------------------------------

class TileLines:
    """Snaps tile lines (keyed by pull.tiles.line_key) onto segments, with a disk cache."""

    def __init__(self, net: Network, directory: Path, maps: LineMaps):
        self.net, self.dir, self.maps = net, directory, maps
        self._geoms: dict[str, list] | None = None

    def segments(self, key: str) -> list:
        hit = self.maps.get(key)
        if hit is not None:
            return hit
        if self._geoms is None:  # load geometry.jsonl once, only when some line isn't cached
            self._geoms = {}
            path = self.dir / "geometry.jsonl"
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        g = json.loads(line)
                        self._geoms[g["key"]] = g["coords"]
        coords = self._geoms.get(key)
        mapped = [[sid, round(m, 1)] for sid, m in self.net.snap_line([tuple(c) for c in coords])] if coords else []
        self.maps.put(key, mapped)
        return mapped


def read_tomtom(run: SourceRun, row: dict, lines: TileLines) -> None:
    if not row.get("ok"):
        return
    t = parse_time(row["polled_at"])
    if row.get("style") == "relative":  # fraction of free flow per line, every 6 h
        for key, rel, *_ in row.get("lines") or []:
            if isinstance(rel, (int, float)):
                run.state.tomtom_relative[key] = [rel, t.isoformat()]
        return
    if not run.in_window(t):
        return
    b = bucket_of(t)
    for key, kmh, _cls, closed in row.get("lines") or []:
        if not isinstance(kmh, (int, float)) and not closed:
            continue
        mph = 0.0 if closed else kmh * KMH_TO_MPH
        if not 0 <= mph <= MAX_MPH:
            run.stats["implausible"] += 1
            continue
        ff = None
        rel = run.state.tomtom_relative.get(key)
        if rel and not closed and rel[0] >= TOMTOM_MIN_RELATIVE \
                and timedelta(0) <= t - datetime.fromisoformat(rel[1]) <= TOMTOM_RELATIVE_MAX_AGE:
            ff = min(mph / rel[0], MAX_MPH)
        segs = lines.segments(key)
        if not segs:
            run.stats["unmatched_lines"] += 1
        for sid, m in segs:
            a = run.acc[(b, sid)]
            a.speed(mph, m)
            if ff:
                a.free_flow(ff, m)
        run.stats["readings"] += bool(segs)


def read_mapbox_tiles(run: SourceRun, row: dict, lines: TileLines) -> None:
    if not row.get("ok"):
        return
    t = parse_time(row["polled_at"])
    if not run.in_window(t):
        return
    b = bucket_of(t)
    for key, level, _cls, closed in row.get("lines") or []:
        ratio = 1.0 if closed else TILE_CONGESTION_RATIO.get(level)
        if ratio is None:  # "unknown" or missing
            continue
        segs = lines.segments(key)
        if not segs:
            run.stats["unmatched_lines"] += 1
        for sid, m in segs:
            run.acc[(b, sid)].ratio(ratio, m)
        run.stats["readings"] += bool(segs)


def route_plan_id(provider: str, coords: list) -> str:
    blob = json.dumps([[round(x, 5), round(y, 5)] for x, y in coords], separators=(",", ":"))
    return f"{provider}:" + hashlib.sha1(blob.encode()).hexdigest()[:20]


def read_mapbox_route(run: SourceRun, row: dict) -> None:
    if not row.get("ok"):
        return
    t = parse_time(row["polled_at"])
    if not run.in_window(t):
        return
    seg, coords = row.get("segments") or {}, row.get("geometry") or []
    dist, dur = seg.get("distance_m") or [], seg.get("duration_s") or []
    if not dist or len(dur) != len(dist) or len(coords) != len(dist) + 1:
        run.stats["bad_rows"] += 1
        return
    per_edge: dict[str, list[float]] = {}
    order: list[str] = []
    for i, (d, s) in enumerate(zip(dist, dur)):
        sid = run.net.snap_piece(tuple(coords[i][:2]), tuple(coords[i + 1][:2]))
        if sid is None:
            run.stats["unmatched_pieces"] += 1
            continue
        if not order or order[-1] != sid:
            order.append(sid)
        if d and s and d > 0 and s > 0:
            acc = per_edge.setdefault(sid, [0.0, 0.0])
            acc[0] += d
            acc[1] += s
    b = bucket_of(t)
    for sid, (metres, secs) in per_edge.items():
        if metres < MAPBOX_MIN_COVERAGE * run.net.edges[sid].length_m:
            continue  # route starts or ends partway along this edge
        mph = metres / secs * MPS_TO_MPH
        if mph <= MAX_MPH:
            run.acc[(b, sid)].speed(mph, secs)  # time-weighted mean = total metres / total seconds
            run.stats["readings"] += 1

    corridor, direction = row.get("corridor"), row.get("direction")
    plan_id = route_plan_id("mapbox", coords)
    run.plans[plan_id] = {
        "_id": plan_id, "kind": "probe", "provider": "mapbox", "corridor_id": corridor, "direction": direction,
        "geometry": {"type": "LineString", "coordinates": [list(c[:2]) for c in coords]},
        "segment_ids": order, "last_seen_at": t,
        "last_summary": {"duration_sec": row.get("duration_s"), "typical_duration_sec": row.get("duration_typical_s"),
                         "distance_m": row.get("distance_m")},
    }
    run.eta_rows.append({
        "time": t, "corridor_id": corridor, "direction": direction, "provider": "mapbox", "route_idx": 0,
        "departure_time": t, "duration_sec": row.get("duration_s"),
        "typical_duration_sec": row.get("duration_typical_s"), "static_duration_sec": None,
        "distance_m": row.get("distance_m"), "route_plan_id": plan_id, "event_id": None,
    })


class MuniReader:
    """Speed between consecutive fixes of one in-service vehicle. Fixes before the window
    only seed the previous position, so a vehicle's first move after a watermark still counts."""

    def __init__(self) -> None:
        self.last: dict[str, tuple[datetime, LonLat, Any]] = {}

    def __call__(self, run: SourceRun, row: dict) -> None:
        vid, line = row.get("vehicle"), row.get("line")
        try:
            t = parse_time(row["polled_at"])
            pos = (float(row["lon"]), float(row["lat"]))
        except (KeyError, TypeError, ValueError):
            run.stats["bad_rows"] += 1
            return
        if not vid:
            return
        prev = self.last.get(vid)
        self.last[vid] = (t, pos, line)
        if line is None or prev is None or prev[2] != line or not run.in_window(t):
            return
        gap = (t - prev[0]).total_seconds()
        if not 0 < gap <= MUNI_MAX_GAP_S:
            return
        hop = haversine_m(prev[1], pos)
        if hop > MUNI_MAX_HOP_M:
            run.stats["gps_jumps"] += 1
            return
        if hop < MUNI_STOPPED_M:
            bearing = row.get("bearing")
            if not isinstance(bearing, (int, float)):
                return
            sid = run.net.index.nearest_heading(pos, float(bearing), 20.0, 45.0)
        else:
            sid = run.net.snap_piece(prev[1], pos)
        if sid is None:
            run.stats["unmatched_pieces"] += 1
            return
        run.acc[(bucket_of(t), sid)].speed(hop / gap * MPS_TO_MPH, 1.0)
        run.stats["readings"] += 1


# --- driver --------------------------------------------------------------------

class TrafficJob:
    def __init__(self, net: Network, state: State, sink: Sink, *, graph_sig: str,
                 now: datetime | None = None, dirs: dict[str, Path] | None = None):
        self.net, self.state, self.sink = net, state, sink
        self.graph_sig = graph_sig
        self.now = now or datetime.now(timezone.utc)
        self.dirs = {**DIRS, **(dirs or {})}

    def run(self, sources: tuple[str, ...] = SOURCES) -> dict[str, dict]:
        end = bucket_of(self.now - LAG)
        report = {}
        for source in sources:
            report[source] = self._run_source(source, end)
        self.state.save()
        return report

    def _run_source(self, source: str, end: datetime) -> dict:
        start = self.state.watermark(source)
        directory = self.dirs[source]
        # Muni needs the fix just before the window to measure the first move in it.
        since = (start - timedelta(seconds=MUNI_MAX_GAP_S)).date() if start else None
        files = day_files(directory, since, end.date())
        run = SourceRun(source, self.net, self.state, start, end)
        lines = maps = None
        if source in ("tomtom", "mapbox_tiles"):
            maps = LineMaps(self.state.dir, source, self.graph_sig)
            lines = TileLines(self.net, directory, maps)
        muni = MuniReader() if source == "muni" else None
        written = eta = 0
        for path in files:
            for row in read_jsonl(path, run.stats):
                run.stats["rows"] += 1
                try:
                    if source == "tomtom":
                        read_tomtom(run, row, lines)
                    elif source == "mapbox_tiles":
                        read_mapbox_tiles(run, row, lines)
                    elif source == "mapbox_route":
                        read_mapbox_route(run, row)
                    else:
                        muni(run, row)
                except (KeyError, TypeError, ValueError) as e:  # one malformed row never stops a run
                    run.stats["bad_rows"] += 1
                    run.stats.setdefault("first_error", f"{path.name}: {type(e).__name__}: {e}")
            # Buckets never cross midnight UTC, so everything read from this day file is final.
            rows = run.rows()
            if rows:
                self.sink.write_traffic(rows)
                written += len(rows)
            if run.eta_rows:
                self.sink.write_route_eta(run.eta_rows)
                eta += len(run.eta_rows)
                run.eta_rows = []
            if run.plans:
                self.sink.write_route_plans(list(run.plans.values()))
                run.plans = {}
            if maps:
                maps.save()
        if files:
            self.state.set_watermark(source, end)
        return {"files": len(files), "window": [start, end], "traffic_rows": written, "route_eta_rows": eta,
                **dict(run.stats)}
