"""Ingestion worker CLI.

    python -m worker bootstrap                 # Tiger schema (contract + worker additions), Mongo indexes, road_segments
    python -m worker run segments              # OSM graph (+ DataSF cnn / speed limits) -> Mongo road_segments
    python -m worker run traffic               # pull.poll JSONL -> Tiger traffic_metrics + route_eta_metrics, Mongo route_plans
    python -m worker run traffic --source tomtom --dry-run
    python -m worker schedule                  # traffic every 10 min; segments again whenever the OSM graph changes

Needs the OSM graph first: `python -m pull osm_drive_graph` (writes data/raw/osm_drive_graph.graphml).
`--dry-run` touches no database and prints what would be written; watermarks aren't saved.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from datasf.client import load_dotenv
from pull import DATA_DIR, ENV_FILE

from .db import CombinedSink, ConfigError, DryRunSink, MongoSink, TigerSink
from .network import Network, road_segment_doc
from .state import STATE_DIR, State
from .traffic import BUCKET, SOURCES, TrafficJob

GRAPHML = DATA_DIR / "osm_drive_graph.graphml"


def graph_sig(path: Path) -> str:
    st = path.stat()
    return f"{st.st_size}-{int(st.st_mtime)}"


def load_network() -> Network:
    if not GRAPHML.exists():
        raise ConfigError(f"no OSM graph at {GRAPHML}: run `python -m pull osm_drive_graph` first")
    return Network.load(GRAPHML, DATA_DIR / "streets.json", DATA_DIR / "speed_limits.json")


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
    return report


def bootstrap(dry_run: bool) -> dict:
    out: dict = {}
    if dry_run:
        out["tiger_schema"] = "skipped (dry run)"
    else:
        out["tiger_schema"] = TigerSink().apply_schema()
        MongoSink().ensure_indexes()
        out["mongo_indexes"] = "ok"
    out["segments"] = run_segments(load_network(), dry_run)
    return out


def schedule() -> None:
    net, sig = load_network(), graph_sig(GRAPHML)
    run_segments(net, dry_run=False)
    while True:
        started = time.monotonic()
        if graph_sig(GRAPHML) != sig:  # weekly `pull osm_drive_graph` refresh
            net, sig = load_network(), graph_sig(GRAPHML)
            print(json.dumps({"segments": run_segments(net, dry_run=False)}), flush=True)
        try:
            report = run_traffic(net, SOURCES, dry_run=False)
            print(json.dumps({"at": datetime.now(timezone.utc), "traffic": report}, default=str), flush=True)
        except Exception as e:  # a DB blip shouldn't kill the worker; the watermark didn't move
            print(json.dumps({"at": datetime.now(timezone.utc), "error": f"{type(e).__name__}: {e}"},
                             default=str), file=sys.stderr, flush=True)
        time.sleep(max(0.0, BUCKET.total_seconds() - (time.monotonic() - started)))


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="python -m worker", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bootstrap")
    b.add_argument("--dry-run", action="store_true")
    r = sub.add_parser("run")
    r.add_argument("job", choices=["segments", "traffic"])
    r.add_argument("--source", action="append", choices=SOURCES, help="traffic source (repeatable; default all)")
    r.add_argument("--dry-run", action="store_true")
    sub.add_parser("schedule")
    args = p.parse_args(argv)

    load_dotenv(ENV_FILE)
    try:
        if args.cmd == "bootstrap":
            out = bootstrap(args.dry_run)
        elif args.cmd == "schedule":
            schedule()
            return 0
        elif args.job == "segments":
            out = run_segments(load_network(), args.dry_run)
        else:
            out = run_traffic(load_network(), tuple(args.source or SOURCES), args.dry_run)
    except ConfigError as e:
        print(e, file=sys.stderr)
        return 2
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(0)
