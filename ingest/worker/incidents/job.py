"""Closures and incidents: `python -m pull` snapshots -> Mongo `road_incidents`.

snapshot rows -> normalize -> dedupe within source -> enrich (cnn geometry, OSM road_segment_ids,
optional geocode) -> validate (bad rows -> data/quarantine/<source>.jsonl) -> dedupe across
sources -> upsert on source + source_id. One bad row never stops a batch.
(Pipeline shape and rules from ingestion-workers-v1.)
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from ..geo import haversine_m, line_midpoint
from ..network import Network
from . import dedupe
from .adapters import NORMALIZERS
from .geom import StreetIndex, _lines, point
from .records import SCHEMA_VERSION, Record, dumps
from .validate import validate

SOURCES = tuple(NORMALIZERS)

POINT_M = 25.0       # a point lies on every edge within this of the nearest one...
POINT_TIE_M = 5.0    # ...that is at most this much further (an intersection touches all approaches)
LINE_SAMPLE_M = 20.0
LINE_M = 15.0        # a line covers an edge whose midpoint is within this of the line
MAX_SEGMENT_IDS = 200


class Sink(Protocol):
    def write_road_incidents(self, items: list[tuple[dict, dict]]) -> None: ...


def load_snapshot(raw_dir: Path, name: str) -> dict | None:
    path = raw_dir / f"{name}.json"
    if not path.exists():
        return None
    snap = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(snap, dict) or not isinstance(snap.get("records"), list):
        raise ValueError(f"{path.name}: not a pull snapshot (needs a 'records' list)")
    return snap


def _pulled_at(value: Any) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except ValueError:
        return None


# --- road_segment_ids ---------------------------------------------------------

def _samples(line: list) -> list:
    out = []
    for a, b in zip(line, line[1:]):
        steps = max(1, int(haversine_m(a, b) // LINE_SAMPLE_M))
        out += [(a[0] + i / steps * (b[0] - a[0]), a[1] + i / steps * (b[1] - a[1])) for i in range(steps)]
    return out + line[-1:]


def segment_ids_for(geom: dict | None, net: Network) -> list[str]:
    """OSM edges a closure/incident lies on. Points: the nearest edge and every edge within a
    few metres of it. Lines: edges whose midpoint lies on the line (not the cross streets)."""
    if not geom:
        return []
    if geom["type"] in ("Point", "MultiPoint"):
        pts = [geom["coordinates"]] if geom["type"] == "Point" else geom["coordinates"]
        ids: set[str] = set()
        for p in pts:
            hits = net.index.near(tuple(p), POINT_M)
            if hits:
                ids.update(k for d, k, _ in hits if d <= hits[0][0] + POINT_TIE_M)
        return sorted(ids)[:MAX_SEGMENT_IDS]
    lines = _lines(geom)
    if not lines and geom["type"] == "Polygon":
        lines = [[tuple(p) for p in geom["coordinates"][0]]]
    elif not lines and geom["type"] == "MultiPolygon":
        lines = [[tuple(p) for p in poly[0]] for poly in geom["coordinates"]]
    line_index = type(net.index)()
    for i, line in enumerate(lines):
        line_index.add(str(i), line)
    candidates = {k for line in lines for p in _samples(line) for _, k, _ in net.index.near(p, LINE_M)}
    keep = [k for k in candidates if (m := line_midpoint(net.edges[k].coords)) and line_index.near(m, LINE_M)]
    return sorted(keep)[:MAX_SEGMENT_IDS]


# --- documents ----------------------------------------------------------------

def road_incident_doc(r: Record, now: datetime) -> tuple[dict, dict]:
    """(upsert filter, document). AGENTS.md keys: source+source_id, location, start_time/end_time,
    road_segment_ids. `is_closure` = closed to traffic (hard routing constraint)."""
    a, ref = r.attributes, r.road_ref or {}
    doc = {
        "source_id": r.source_id,
        "incident_type": r.kind,  # closure | incident
        "category": a.get("closure_type") or a.get("category"),
        "is_closure": bool(a.get("is_closure")),
        "location": r.geometry,
        "start_time": r.valid_from,
        "end_time": r.valid_to,
        "reported_at": r.observed_at,
        "cnn": ref.get("cnn"),
        "cnn_match": ref.get("match"),
        "details": a,
        "source_fields": r.source_fields,
        "source": r.source,
        "location_status": r.location_status,
        "provenance": r.provenance(),
        "schema_version": SCHEMA_VERSION,
        "last_ingested_at": now,
    }
    if "road_segment_ids" in r.computed:
        doc["road_segment_ids"] = r.road_segment_ids
    return {"source": r.source, "source_id": r.source_id}, doc


# --- job ------------------------------------------------------------------------

class IncidentJob:
    def __init__(self, raw_dir: Path, sink: Sink, *, net: Network | None = None, geocoder: Any = None,
                 out_dir: Path | None = None, now: datetime | None = None):
        self.raw_dir, self.sink, self.net, self.geocoder = raw_dir, sink, net, geocoder
        self.out_dir = out_dir or raw_dir.parent
        self.now = now or datetime.now(timezone.utc)
        self.streets: StreetIndex | None = None

    def _enrich(self, r: Record, st: Counter) -> None:
        if r.road_ref and self.streets and r.road_ref.get("match") == "unknown":
            r.road_ref["match"] = self.streets.classify(r.road_ref["cnn"])
        if r.geometry is None and r.road_ref and self.streets:
            g = self.streets.geometry_for(r.road_ref["cnn"])
            if g:
                r.geometry, r.location_status = g, "from_cnn"
        if r.geometry and r.geometry["type"] == "Point" and r.road_ref is None and self.streets \
                and r.kind == "closure":
            hit = self.streets.nearest_segment(tuple(r.geometry["coordinates"]))
            if hit:
                r.road_ref = {"cnn": hit[0], "match": "nearest_segment", "distance_m": hit[1]}
        if r.geometry is None and r.location_status == "unlocated" and r.geocode_query and self.geocoder:
            hit = self.geocoder.geocode(r.geocode_query)
            if hit:
                r.geometry, r.location_status = point(*hit), "geocoded"
                r.attributes["geocode"] = {"provider": self.geocoder.name, "query": r.geocode_query}
            else:
                st["geocode_missed"] += 1
        if self.net is not None:
            r.road_segment_ids = segment_ids_for(r.geometry, self.net)
            r.computed.add("road_segment_ids")

    def _source(self, name: str, snap: dict, st: Counter, quarantine: list[dict]) -> list[Record]:
        fn, pulled_at = NORMALIZERS[name], _pulled_at(snap.get("pulled_at"))
        normalized: list[tuple[int, Any, Record]] = []
        for i, row in enumerate(snap["records"]):
            st["raw"] += 1
            try:
                if not isinstance(row, dict):
                    raise ValueError(f"row is {type(row).__name__}, not an object")
                r = fn(row)
            except Exception as e:  # malformed row: quarantine it, keep the batch going
                quarantine.append({"source": name, "index": i, "errors": [f"{type(e).__name__}: {e}"], "raw": row})
                continue
            if r is None:
                st["filtered"] += 1
                continue
            r.pulled_at = pulled_at
            normalized.append((i, row, r))
        unique, st["duplicates"] = dedupe.within_source(r for _, _, r in normalized)
        keep = {id(r) for r in unique}
        out = []
        for i, row, r in normalized:
            if id(r) not in keep:
                continue
            try:
                self._enrich(r, st)
                errors = validate(r)
            except Exception as e:
                errors = [f"{type(e).__name__}: {e}"]
            if errors:
                quarantine.append({"source": name, "index": i, "id": r.id, "errors": errors, "raw": row})
                continue
            st[r.location_status] += 1
            st["on_road_segments"] += bool(r.road_segment_ids)
            st["is_closure"] += bool(r.attributes.get("is_closure"))
            out.append(r)
        st["rejected"] = len(quarantine)
        st["normalized"] = len(out)
        return out

    def run(self, sources: tuple[str, ...] = SOURCES) -> dict[str, dict]:
        report: dict[str, dict] = {}
        streets = load_snapshot(self.raw_dir, "streets")
        self.streets = StreetIndex.from_rows(streets["records"]) if streets else None
        records: list[Record] = []
        quarantine: dict[str, list[dict]] = defaultdict(list)
        stats: dict[str, Counter] = {}
        for name in sources:
            st = stats[name] = Counter()
            try:
                snap = load_snapshot(self.raw_dir, name)
            except (OSError, ValueError) as e:
                report[name] = {"status": "failed", "error": str(e)}
                continue
            if snap is None:
                report[name] = {"status": "missing", "note": f"not pulled yet (python -m pull {name})"}
                continue
            records += self._source(name, snap, st, quarantine[name])
        kept, _ = dedupe.cross_source(records)
        kept_ids = {r.id for r in kept}
        for r in records:
            if r.id not in kept_ids:
                stats[r.source]["merged_into_other_source"] += 1
        if kept:
            self.sink.write_road_incidents([road_incident_doc(r, self.now) for r in kept])
        self._write_quarantine(sources, quarantine)
        for name, st in stats.items():
            report.setdefault(name, {"status": "ok", **dict(st)})
        report["_notes"] = [n for n in (
            None if self.streets else "no streets snapshot: cnn-only permits stay unlocated",
            None if self.net else "no OSM graph: road_segment_ids not computed",
            None if self.geocoder else "geocoding off (GEOCODER=mapbox to enable)") if n]
        return report

    def _write_quarantine(self, sources: tuple[str, ...], quarantine: dict[str, list[dict]]) -> None:
        qdir = self.out_dir / "quarantine"
        for name in sources:
            path, rows = qdir / f"{name}.jsonl", quarantine.get(name) or []
            if rows:
                qdir.mkdir(parents=True, exist_ok=True)
                path.write_text("".join(dumps(q) + "\n" for q in rows), encoding="utf-8")
            elif path.exists():
                path.unlink()  # stale quarantine from an earlier run
