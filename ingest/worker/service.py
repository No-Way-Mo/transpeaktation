"""The worker's jobs as plain functions. `python -m worker` (CLI) and `python -m worker serve` (HTTP trigger) both call
these, so there is one ingestion implementation.

    refresh(("incidents",))   # re-pull DataSF / Caltrans / CHP snapshots, normalize, dedupe, geocode -> Mongo
    refresh(("traffic",))     # pull.poll JSONL -> Tiger traffic_metrics (+ Mongo route_plans)
    refresh(("events",))      # re-pull PredictHQ, normalize -> Mongo events + venues
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from pull import DATA_DIR, MANIFEST

from .db import CombinedSink, ConfigError, DryRunSink, MongoSink, TigerSink
from .events import SOURCE as EVENT_SOURCE, EventJob
from .incidents import geocode
from .incidents.job import SOURCES as INCIDENT_SOURCES, IncidentJob
from .network import Network, road_segment_doc
from .state import STATE_DIR, State
from .traffic import SOURCES, TrafficJob

GRAPHML = DATA_DIR / "osm_drive_graph.graphml"
JOBS = ("incidents", "traffic", "events")


def graph_sig(path: Path) -> str:
    st = path.stat()
    return f"{st.st_size}-{int(st.st_mtime)}"


def load_network() -> Network:
    if not GRAPHML.exists():
        raise ConfigError(f"no OSM graph at {GRAPHML}: run `python -m pull osm_drive_graph` first")
    return Network.load(GRAPHML, DATA_DIR / "streets.json", DATA_DIR / "speed_limits.json")


_net: tuple[str, Network] | None = None


def cached_network() -> Network | None:
    """The OSM graph, loaded once and reloaded when the file changes (weekly refresh). None if never pulled."""
    global _net
    if not GRAPHML.exists():
        return None
    sig = graph_sig(GRAPHML)
    if _net is None or _net[0] != sig:
        _net = (sig, load_network())
    return _net[1]


def run_segments(net: Network, dry_run: bool) -> dict:
    docs = [road_segment_doc(e) for e in net.edges.values()]
    sink = DryRunSink() if dry_run else MongoSink()
    sink.write_road_segments(docs)
    out = {"road_segments": len(docs), "with_cnn": sum(1 for e in net.edges.values() if e.cnn),
           "with_posted_limit": sum(1 for e in net.edges.values() if e.speed_limit_mph)}
    if dry_run:
        out["sample"] = sink.samples.get("road_segments", [])[:1]
    return out


def run_traffic(net: Network, sources: tuple[str, ...], dry_run: bool, state_dir: Path = STATE_DIR) -> dict:
    state = State(state_dir)
    if dry_run:
        sink = DryRunSink()
        state.save = lambda: None  # a dry run must not move watermarks
    else:
        try:
            mongo = MongoSink()
        except ConfigError as e:  # route plans are optional; traffic rows are the point
            print(f"mongo unavailable, route_plans skipped: {e}", file=sys.stderr)
            mongo = None
        sink = CombinedSink(TigerSink(), mongo)
    report = TrafficJob(net, state, sink, graph_sig=graph_sig(GRAPHML)).run(sources)
    if dry_run:
        report["_dry_run"] = {"would_write": dict(sink.counts), "samples": sink.samples}
    else:
        report["_written"] = {**sink.tiger.counts, **(sink.mongo.counts if sink.mongo else {})}
    return report


def refresh_snapshots(sources: tuple[str, ...] = INCIDENT_SOURCES) -> dict[str, dict]:
    """Re-pull feeds with `python -m pull`'s own code. Returns each feed's manifest entry
    (status ok | skip | fail, row count, seconds); a failed feed doesn't stop the others."""
    from pull.__main__ import main as pull_main

    pull_main(list(sources))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    return {name: manifest.get(name, {"status": "missing"}) for name in sources}


def run_incidents(net: Network | None, dry_run: bool, use_geocoder: bool = True) -> dict:
    geocoder, why = geocode.from_env(DATA_DIR.parent / "cache" / "geocode.json") if use_geocoder \
        else (None, "geocoding disabled (--no-geocode)")
    sink = DryRunSink() if dry_run else MongoSink()
    report = IncidentJob(DATA_DIR, sink, net=net, geocoder=geocoder).run()
    if geocoder is not None:
        geocoder.save()
    report["_geocoder"] = why
    if dry_run:
        report["_dry_run"] = {"would_write": dict(sink.counts), "sample": sink.samples.get("road_incidents", [])[:1]}
    else:
        report["_written"] = dict(sink.counts)
    return report


def events_due(every: timedelta, now: datetime | None = None) -> bool:
    """True when the last PredictHQ pull attempt (any status, from the pull manifest) is older than `every`. Read from
    disk, not kept in memory, so restarts (every redeploy) don't each spend a pull of the free tier."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    last = (manifest.get(EVENT_SOURCE) or {}).get("pulled_at")
    return last is None or (now or datetime.now(timezone.utc)) - datetime.fromisoformat(last) >= every


def run_events(dry_run: bool) -> dict:
    sink = DryRunSink() if dry_run else MongoSink()
    report = EventJob(DATA_DIR, sink).run()
    if dry_run:
        report["_dry_run"] = {"would_write": dict(sink.counts), "sample": sink.samples.get("events", [])[:1]}
    else:
        report["_written"] = dict(sink.counts)
    return report


# --- one refresh = the jobs the scheduler runs each tick ---------------------------------------------------------

_SECRET_PATTERNS = (
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s:@]*:[^@\s]*@"), r"\1***@"),        # scheme://user:pass@
    (re.compile(r"(?i)\b(token|app_token|access_token|api_key|apikey|key|password|pwd)=[^&\s\"']+"), r"\1=***"),
)


def redact(value: Any) -> Any:
    """Strip credentials that feeds or drivers put in error strings (URIs with passwords, ?token=...)."""
    if isinstance(value, str):
        for pat, rep in _SECRET_PATTERNS:
            value = pat.sub(rep, value)
        return value
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


def safe_error(e: BaseException) -> str:
    """Our own ConfigError messages are written to be shown; anything else (driver, network) is reduced to its type,
    because those messages can carry hostnames or connection strings."""
    return redact(str(e)) if isinstance(e, ConfigError) else type(e).__name__


def refresh(jobs: Iterable[str] = ("incidents",), *, pull: bool = True, dry_run: bool = False,
            use_geocoder: bool = True) -> dict:
    """Run each job once, in order, with the CLI's semantics: a feed that fails to pull is reported and the rest carry
    on; a job that raises (no DB configured, DB down) is reported as failed without stopping the next job.

    Returns {"started_at", "finished_at", "ok", "jobs": {name: {"status": ok | failed, ...report}}, "failures": [...]}
    using only what the pull manifest and the jobs' own reports know."""
    jobs = tuple(dict.fromkeys(jobs))
    bad = [j for j in jobs if j not in JOBS]
    if bad:
        raise ValueError(f"unknown job(s) {bad}; choose from {list(JOBS)}")
    out: dict[str, Any] = {"started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                           "dry_run": dry_run, "jobs": {}}
    failures: list[dict] = []
    for name in jobs:
        try:
            if name == "incidents":
                step: dict[str, Any] = {}
                if pull:
                    step["pulled"] = refresh_snapshots()
                    failures += [{"job": name, "source": s, "stage": "pull", "error": e.get("error", e["status"])}
                                 for s, e in step["pulled"].items() if e.get("status") in ("fail", "missing")]
                step["report"] = run_incidents(cached_network(), dry_run, use_geocoder)
                failures += [{"job": name, "source": s, "stage": "normalize", "error": r.get("error", r["status"])}
                             for s, r in step["report"].items()
                             if isinstance(r, dict) and r.get("status") in ("failed", "missing")]
            elif name == "events":
                step = {}
                if pull:
                    step["pulled"] = refresh_snapshots((EVENT_SOURCE,))
                    got = step["pulled"][EVENT_SOURCE]
                    if got.get("status") != "ok":  # skip (no token) or fail: keep what Mongo has, don't re-stamp it
                        if got.get("status") != "skip":
                            failures.append({"job": name, "source": EVENT_SOURCE, "stage": "pull",
                                             "error": got.get("error", got.get("status"))})
                        step["report"] = {"status": "not_run", "note": "no new pull; Mongo keeps the last one"}
                        out["jobs"][name] = {"status": "ok", **step}
                        continue
                step["report"] = rep = run_events(dry_run)
                if rep.get("status") == "failed":
                    failures.append({"job": name, "source": EVENT_SOURCE, "stage": "normalize", "error": rep["error"]})
                elif (rep.get("meta") or {}).get("truncated"):
                    failures.append({"job": name, "source": EVENT_SOURCE, "stage": "pull",
                                     "error": "truncated: more pages than PHQ_MAX_PAGES; vanished events not archived"})
            else:
                net = cached_network()
                if net is None:
                    raise ConfigError(f"no OSM graph at {GRAPHML}: run `python -m pull osm_drive_graph` first")
                step = {"report": run_traffic(net, SOURCES, dry_run)}
            out["jobs"][name] = {"status": "ok", **step}
        except Exception as e:  # same as the scheduler: one job's failure is reported, the next job still runs
            print(f"refresh: job {name} failed: {type(e).__name__}: {redact(str(e))}", file=sys.stderr, flush=True)
            out["jobs"][name] = {"status": "failed", "error": safe_error(e)}
            failures.append({"job": name, "stage": "run", "error": safe_error(e)})
    out["failures"] = failures
    out["ok"] = all(j["status"] == "ok" for j in out["jobs"].values())
    out["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return redact(out)
