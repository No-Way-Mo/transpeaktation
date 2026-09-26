"""raw snapshot / time-series rows -> normalize -> dedupe (within source) -> enrich
(cnn, OSM edges, geocode) -> validate -> cross-source dedupe -> classify destination ->
persist. One bad row never stops a batch: it is quarantined."""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pull import DATA_DIR

from . import dedupe, link, log
from .adapters import LAYERS, NORMALIZERS, REQUIRES_OSM, TIMESERIES, UNSUPPORTED
from .context import Context
from .geo import StreetIndex, point
from .osm_graphml import edge_index
from .records import Record, dumps
from .storage import MONGO, TIGER, debug_doc, destination, mongo_doc, tiger_row
from .validate import validate
from .writers import ConfigError, MongoWriter, TigerWriter

INGEST_DATA = DATA_DIR.parent


@dataclass
class SourceStats:
    source: str
    layer: str
    status: str = "pending"   # ok | missing | skipped | unsupported | blocked | failed
    note: str = ""
    raw: int = 0
    normalized: int = 0
    filtered: int = 0
    rejected: int = 0
    duplicates: int = 0
    merged: int = 0
    from_cnn: int = 0
    snapped: int = 0
    linked: int = 0           # incidents given OSM road_segment_ids / OSM edges matched to a cnn
    geocoded: int = 0
    geocode_missed: int = 0
    withheld: int = 0
    unlocated: int = 0
    stored: int = 0           # records handed to a store (or that would be, in dry run)
    unrouted: int = 0         # valid records with no destination in the contract
    mongo_new: int = 0
    mongo_updated: int = 0
    tiger_rows: int = 0
    tiger_skipped: int = 0    # already stored by an earlier run
    write_errors: int = 0


@dataclass
class RunResult:
    started_at: datetime
    dry_run: bool
    stats: dict[str, SourceStats]
    records: list[Record] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    exit_code: int = 0

    def summary(self) -> dict[str, Any]:
        return {"started_at": self.started_at, "dry_run": self.dry_run, "exit_code": self.exit_code,
                "notes": self.notes, "sources": {k: asdict(v) for k, v in self.stats.items()}}


def select(args: list[str]) -> list[str]:
    """Same selection rules as `python -m pull`: nothing = all; a layer name; source names."""
    layers = set(LAYERS.values())
    unknown = [a for a in args if a not in LAYERS and a not in layers]
    if unknown:
        raise ValueError(f"unknown: {unknown}. layers: {sorted(layers)}; sources: {list(LAYERS)}")
    return [n for n, layer in LAYERS.items() if not args or n in args or layer in args]


def load_snapshot(raw_dir: Path, name: str) -> dict | None:
    path = raw_dir / f"{name}.json"
    if not path.exists():
        return None
    snap = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(snap, dict) or not isinstance(snap.get("records"), list):
        raise ValueError(f"{path.name}: not a pull snapshot (needs a 'records' list)")
    return snap


def load_timeseries(ts_dir: Path, name: str) -> dict | None:
    """All *.jsonl rows under ts_dir as one pseudo-snapshot. Unparseable lines stay as strings
    so they are quarantined like any malformed row."""
    files = sorted(ts_dir.glob("*.jsonl")) if ts_dir.is_dir() else []
    if not files:
        return None
    rows: list[Any] = []
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    rows.append(line)
    return {"source": name, "pulled_at": None, "records": rows, "meta": {"files": [f.name for f in files]}}


def _parse_pulled_at(value: Any) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except ValueError:
        return None


class Pipeline:
    def __init__(self, raw_dir: Path = DATA_DIR, *, out_dir: Path = INGEST_DATA, dry_run: bool = False,
                 dump: bool = False, geocoder: Any = None, mongo: MongoWriter | None = None,
                 tiger: TigerWriter | None = None, store_errors: dict[str, str] | None = None,
                 now: datetime | None = None, timeseries_dirs: dict[str, Path] | None = None):
        self.raw_dir = raw_dir
        self.timeseries_dirs = {n: d for n, (_, d) in TIMESERIES.items()} | (timeseries_dirs or {})
        self.out_dir = out_dir
        self.dry_run = dry_run
        self.dump = dump or dry_run
        self.geocoder = geocoder
        self.mongo = mongo
        self.tiger = tiger
        self.store_errors = store_errors or {}  # store -> why it is unavailable
        self.now = now or datetime.now(timezone.utc)
        self.store_blocked = False  # a record needed a store that wasn't available
        self.speed_limits: dict[str, dict] | None = None

    # --- context ------------------------------------------------------------------

    def _context(self, names: list[str]) -> tuple[Context, list[str]]:
        notes = []
        ctx = Context(now=self.now)
        try:
            streets = load_snapshot(self.raw_dir, "streets")
        except (OSError, ValueError) as e:
            streets = None
            notes.append(f"street index unavailable: {e}")
        if streets:
            ctx.streets = StreetIndex.from_rows(streets["records"])
        else:
            notes.append("no streets snapshot: no cnn classification, cnn geometry, or OSM<->cnn match")
        try:
            snap = load_snapshot(self.raw_dir, "osm_drive_graph")
            graphml = self.raw_dir / ((snap or {}).get("meta") or {}).get("graphml", "osm_drive_graph.graphml")
            if graphml.exists():
                ctx.osm = edge_index(graphml)
            else:
                notes.append("no OSM GraphML (python -m pull osm_drive_graph): no road_segment geometry, "
                             "no road_segment_ids on incidents, Mapbox speeds can't be mapped")
        except (OSError, ValueError) as e:
            notes.append(f"OSM graph unreadable: {e}")
        if "osm_drive_graph" in names:
            self.speed_limits = self._load_speed_limits(ctx, notes)
        return ctx, notes

    def _load_speed_limits(self, ctx: Context, notes: list[str]) -> dict[str, dict] | None:
        """cnn -> speed limit from the speed_limits snapshot (embedded in road_segments)."""
        try:
            snap = load_snapshot(self.raw_dir, "speed_limits")
        except (OSError, ValueError) as e:
            notes.append(f"speed limits unavailable: {e}")
            return None
        if not snap:
            return None
        recs = []
        for row in snap["records"]:
            try:
                r = NORMALIZERS["speed_limits"](row, ctx)
            except Exception:  # counted and quarantined when the speed_limits source itself runs
                continue
            if r is not None:
                recs.append(r)
        return link.speed_limits_by_cnn(recs)

    # --- per record ---------------------------------------------------------------

    def _enrich(self, r: Record, ctx: Context, st: SourceStats) -> None:
        streets, osm = ctx.streets, ctx.osm
        if r.road_ref and streets and r.road_ref.get("match") == "unknown":
            r.road_ref["match"] = streets.classify(r.road_ref["cnn"])
        if r.geometry is None and r.road_ref and streets:
            g = streets.geometry_for(r.road_ref["cnn"])
            if g:
                r.geometry, r.location_status = g, "from_cnn"
        if (r.geometry and r.geometry["type"] == "Point" and r.road_ref is None and streets
                and r.kind in ("road_rule", "closure")):
            hit = streets.nearest_segment(tuple(r.geometry["coordinates"]))
            if hit:
                r.road_ref = {"cnn": hit[0], "match": "nearest_segment", "distance_m": hit[1]}
        if r.kind == "road_segment" and r.source == "osm_drive_graph" and streets:
            hit = link.match_cnn(r.geometry, streets)
            r.road_ref = {"cnn": hit[0], "match": "nearest_segment", "distance_m": hit[1]} if hit else None
            r.computed.add("cnn")
            if self.speed_limits is not None:
                r.attributes["speed_limit"] = self.speed_limits.get(hit[0]) if hit else None
                r.computed.add("speed_limit")
        if r.geometry is None and r.location_status == "unlocated" and r.geocode_query and self.geocoder:
            hit = self.geocoder.geocode(r.geocode_query)
            if hit:
                r.geometry, r.location_status = point(*hit), "geocoded"
                r.attributes["geocode"] = {"provider": self.geocoder.name, "query": r.geocode_query}
            else:
                st.geocode_missed += 1
        if r.kind in ("closure", "incident") and osm is not None:
            r.road_segment_ids = link.segment_ids_for(r.geometry, osm)
            r.computed.add("road_segment_ids")

    @staticmethod
    def _tally(r: Record, st: SourceStats) -> None:
        """Location stats, counted only for records that passed validation."""
        st.from_cnn += r.location_status == "from_cnn"
        st.geocoded += r.location_status == "geocoded"
        st.withheld += r.location_status == "withheld"
        st.unlocated += r.location_status == "unlocated"
        nearest = bool(r.road_ref and r.road_ref.get("match") == "nearest_segment")
        if r.kind == "road_segment":
            st.linked += nearest
        else:
            st.snapped += nearest
            st.linked += bool(r.road_segment_ids) and r.kind != "traffic_metric"

    def _normalize_source(self, name: str, snap: dict, ctx: Context, st: SourceStats,
                          quarantine: list[dict]) -> list[Record]:
        fn = NORMALIZERS[name]
        pulled_at = _parse_pulled_at(snap.get("pulled_at"))

        def reject(i: int, row: Any, errors: list[str], r: Record | None = None) -> None:
            st.rejected += 1
            quarantine.append({"source": name, "index": i, "id": r.id if r else None, "errors": errors, "raw": row})

        normalized: list[tuple[int, Any, Record]] = []
        for i, row in enumerate(snap["records"]):
            st.raw += 1
            try:
                if not isinstance(row, dict):
                    raise ValueError(f"row is {type(row).__name__}, not an object")
                r = fn(row, ctx)
            except Exception as e:  # malformed row: quarantine it, keep the batch going
                reject(i, row, [f"{type(e).__name__}: {e}"])
                continue
            if not r:  # None or [] = filtered out
                st.filtered += 1
                continue
            for rec in r if isinstance(r, list) else [r]:
                rec.layer, rec.pulled_at = st.layer, pulled_at
                normalized.append((i, row, rec))

        unique, st.duplicates = dedupe.within_source(r for _, _, r in normalized)
        keep = {id(r) for r in unique}
        out = []
        for i, row, r in normalized:
            if id(r) not in keep:
                continue
            try:
                self._enrich(r, ctx, st)
                errors = validate(r)
            except Exception as e:
                errors = [f"{type(e).__name__}: {e}"]
            if errors:
                reject(i, row, errors, r)
            else:
                self._tally(r, st)
                out.append(r)
        st.normalized = len(out)
        return out

    # --- run ----------------------------------------------------------------------

    def run(self, names: list[str]) -> RunResult:
        res = RunResult(started_at=self.now, dry_run=self.dry_run,
                        stats={n: SourceStats(n, LAYERS[n]) for n in names})
        log.event("run_start", sources=names, dry_run=self.dry_run, raw_dir=str(self.raw_dir))
        manifest = {}
        try:
            manifest_path = self.raw_dir / "_manifest.json"
            if manifest_path.exists():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            res.notes.append(f"manifest unreadable: {e}")
        ctx, notes = self._context(names)
        res.notes += notes
        quarantine: dict[str, list[dict]] = defaultdict(list)
        records: list[Record] = []

        for name in names:
            st = res.stats[name]
            entry = manifest.get(name, {})
            if name in UNSUPPORTED:
                st.status = "unsupported"
                st.note = UNSUPPORTED[name] + (f" [pull: {entry['reason']}]" if entry.get("reason") else "")
                log.event("source_unsupported", logging.WARNING, source=name, reason=st.note)
                continue
            if name in REQUIRES_OSM and ctx.osm is None:
                st.status, st.note = "blocked", REQUIRES_OSM[name]
                log.event("source_blocked", logging.WARNING, source=name, reason=st.note)
                continue
            try:
                snap = (load_timeseries(self.timeseries_dirs[name], name) if name in TIMESERIES
                        else load_snapshot(self.raw_dir, name))
            except (OSError, ValueError) as e:
                st.status, st.note = "failed", f"snapshot unreadable: {e}"
                log.event("source_failed", logging.ERROR, source=name, error=st.note)
                continue
            if snap is None:
                if entry.get("status") == "skip":
                    st.status, st.note = "skipped", f"pull skipped it: {entry.get('reason')}"
                else:
                    st.status = "missing"
                    st.note = entry.get("error") or ("no polls yet (python -m pull.poll)" if name in TIMESERIES
                                                     else f"not pulled yet (python -m pull {name})")
                log.event("source_missing", logging.WARNING, source=name, reason=st.note)
                continue
            if entry.get("status") == "fail":
                st.note = f"latest pull failed ({entry.get('error')}); using older snapshot from {snap.get('pulled_at')}"
                log.event("stale_snapshot", logging.WARNING, source=name, reason=st.note)
            try:
                recs = self._normalize_source(name, snap, ctx, st, quarantine[name])
            except Exception as e:  # adapter bug affecting a whole source: isolate it
                st.status, st.note = "failed", f"{type(e).__name__}: {e}"
                log.event("source_failed", logging.ERROR, source=name, error=st.note)
                continue
            st.status = "ok"
            records += recs
            log.event("source_normalized", source=name, raw=st.raw, normalized=st.normalized,
                      filtered=st.filtered, rejected=st.rejected, duplicates=st.duplicates)

        kept, _ = dedupe.cross_source(records)
        kept_ids = {r.id for r in kept}
        for r in records:
            if r.id not in kept_ids:
                res.stats[r.source].merged += 1
        res.records = kept

        self._persist(res)
        self._write_local(res, quarantine)
        if self.geocoder is not None and hasattr(self.geocoder, "save"):
            self.geocoder.save()

        failed = any(s.status == "failed" or s.write_errors for s in res.stats.values())
        res.exit_code = 1 if failed or self.store_blocked else 0
        log.event("run_done", exit_code=res.exit_code, records=len(kept),
                  rejected=sum(s.rejected for s in res.stats.values()),
                  merged=sum(s.merged for s in res.stats.values()))
        return res

    def _persist(self, res: RunResult) -> None:
        groups: dict[tuple[str, str, str], list[Record]] = defaultdict(list)
        for r in res.records:
            dest = destination(r)
            if dest is None:
                res.stats[r.source].unrouted += 1
                continue
            groups[(dest[0], dest[1], r.source)].append(r)
        for st in res.stats.values():
            if st.unrouted:
                msg = f"{st.unrouted} valid records have no store in the contract (dumped only)"
                st.note = f"{st.note}; {msg}" if st.note else msg
        for (store, target, source), recs in sorted(groups.items()):
            st = res.stats[source]
            st.stored += len(recs)
            if self.dry_run:
                continue
            writer = self.mongo if store == MONGO else self.tiger
            if writer is None:
                why = self.store_errors.get(store, f"{store} writer not configured")
                msg = f"{store} unavailable, {len(recs)} {source} records not persisted: {why}"
                if msg not in res.notes:
                    res.notes.append(msg)
                self.store_blocked = True
                log.event("persist_skipped", logging.ERROR, store=store, target=target, source=source,
                          count=len(recs), reason=why)
                continue
            if store == MONGO:
                w = writer.write(target, (mongo_doc(r, self.now) for r in recs), self.now)
                st.mongo_new += w.written
                st.mongo_updated += w.updated
            else:
                w = writer.write(target, (tiger_row(r) for r in recs))
                st.tiger_rows += w.written
                st.tiger_skipped += w.skipped
            st.write_errors += len(w.errors)
            for err in w.errors[:20]:
                log.event("write_error", logging.ERROR, store=store, target=target, source=source, error=err)
            log.event("persisted", store=store, target=target, source=source, written=w.written,
                      updated=w.updated, skipped=w.skipped, errors=len(w.errors))

    def _write_local(self, res: RunResult, quarantine: dict[str, list[dict]]) -> None:
        qdir = self.out_dir / "quarantine"
        for name in res.stats:
            path = qdir / f"{name}.jsonl"
            rows = quarantine.get(name) or []
            if rows:
                qdir.mkdir(parents=True, exist_ok=True)
                path.write_text("".join(dumps(q) + "\n" for q in rows), encoding="utf-8")
            elif path.exists():
                path.unlink()  # stale quarantine from an earlier run
        if not self.dump:
            return
        ndir = self.out_dir / "normalized"
        ndir.mkdir(parents=True, exist_ok=True)
        by_source: dict[str, list[dict]] = defaultdict(list)
        for r in res.records:
            by_source[r.source].append(debug_doc(r, self.now))
        for name, st in res.stats.items():
            if st.status == "ok":
                (ndir / f"{name}.json").write_text(dumps(by_source.get(name, []), indent=1), encoding="utf-8")
        (ndir / "_run.json").write_text(dumps(res.summary(), indent=2), encoding="utf-8")


def open_writers(dry_run: bool) -> tuple[MongoWriter | None, TigerWriter | None, dict[str, str]]:
    """Connect to whatever is configured; a missing/unreachable store only disables itself."""
    errors: dict[str, str] = {}
    if dry_run:
        return None, None, errors
    mongo = tiger = None
    try:
        mongo = MongoWriter.from_env()
        mongo.ping()
    except Exception as e:  # ConfigError, ImportError, connection/auth errors
        errors[MONGO] = str(e) if isinstance(e, ConfigError) else f"{type(e).__name__}: {e}"
        mongo = None
    try:
        tiger = TigerWriter.from_env()
    except Exception as e:
        errors[TIGER] = str(e) if isinstance(e, ConfigError) else f"{type(e).__name__}: {e}"
    return mongo, tiger, errors
