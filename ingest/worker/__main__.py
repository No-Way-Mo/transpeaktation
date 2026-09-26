"""Ingestion worker CLI.

    python -m worker bootstrap                 # Tiger schema (contract + worker additions), Mongo indexes, road_segments
    python -m worker run segments              # OSM graph (+ DataSF cnn / speed limits) -> Mongo road_segments
    python -m worker run traffic               # pull.poll JSONL -> Tiger traffic_metrics + route_eta_metrics, Mongo route_plans
    python -m worker run traffic --source tomtom --dry-run
    python -m worker run incidents             # pull snapshots (closures, permits, Caltrans, CHP, dispatch) -> Mongo road_incidents
    python -m worker run events                # PredictHQ snapshot -> Mongo events + venues (seeded capacities)
    python -m worker schedule                  # every 10 min: traffic + fresh incident snapshots; events every 6 h;
                                               # segments when the graph changes
    python -m worker backfill --date 2026-09-20  # closures/permits in effect that day (DataSF history) -> road_incidents
    python -m worker serve                     # HTTP trigger: POST /ingest/refresh (needs INGEST_TOKEN; see worker/server.py)

Needs the OSM graph first: `python -m pull osm_drive_graph` (writes data/raw/osm_drive_graph.graphml).
`--dry-run` touches no database and prints what would be written; watermarks aren't saved.
Rows that fail validation go to data/quarantine/<source>.jsonl. Geocoding is opt-in (GEOCODER=mapbox).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from datasf import DATASETS, DataSF, pull as datasf_pull
from datasf.client import load_dotenv
from pull import DATA_DIR, ENV_FILE

from .db import ConfigError, DryRunSink, MongoSink, TigerSink
from .incidents.job import IncidentJob
from .network import Network
from .service import (GRAPHML, cached_network, events_due, load_network, refresh, run_events, run_incidents,
                      run_segments, run_traffic)
from .traffic import BUCKET, SOURCES


# DataSF keeps these after they end, so a past day can be rebuilt. Dispatch, CHP and Caltrans (and traffic) are
# live-only: a past day has them only if the worker was running then.
BACKFILL_SOURCES = ("street_closures", "street_use_permits", "excavation_permits")


def backfill(day: date, net: Network | None, dry_run: bool, client: DataSF | None = None) -> dict:
    """Closures and permits in effect on `day` (SF local), queried as of that morning, into road_incidents."""
    as_of = datetime(day.year, day.month, day.day, tzinfo=ZoneInfo("America/Los_Angeles")).astimezone(timezone.utc)
    raw = DATA_DIR.parent / "backfill" / day.isoformat()
    raw.mkdir(parents=True, exist_ok=True)
    if (DATA_DIR / "streets.json").exists():  # locates cnn-only permits
        shutil.copyfile(DATA_DIR / "streets.json", raw / "streets.json")
    client = client or DataSF(timeout=120)
    for name in BACKFILL_SOURCES:
        rows = datasf_pull(client, DATASETS[name], now=as_of)
        (raw / f"{name}.json").write_text(json.dumps(
            {"source": name, "layer": "planned", "pulled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "count": len(rows), "meta": {"as_of": as_of.isoformat(), "where": DATASETS[name].where_at(as_of)},
             "records": rows}, ensure_ascii=False, default=str), encoding="utf-8")
    sink = DryRunSink() if dry_run else MongoSink()
    report = IncidentJob(raw, sink, net=net, out_dir=raw).run(BACKFILL_SOURCES)
    report["_as_of"] = as_of.isoformat()
    if dry_run:
        report["_dry_run"] = {"would_write": dict(sink.counts)}
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
    net = cached_network() or load_network()  # load_network raises the "pull the graph first" ConfigError
    run_segments(net, dry_run=False)
    # PredictHQ free tier: ~36 requests per pull, so every 6 h by default (PREDICTHQ_EVERY_MIN to change).
    events_every = timedelta(minutes=float(os.environ.get("PREDICTHQ_EVERY_MIN") or 360))
    while True:
        started = time.monotonic()
        jobs = ("traffic", "incidents", *(("events",) if events_due(events_every) else ()))
        if (fresh := cached_network()) is not net:  # weekly `pull osm_drive_graph` refresh
            net = fresh or load_network()
            print(json.dumps({"segments": run_segments(net, dry_run=False)}), flush=True)
        # One implementation for the loop and POST /ingest/refresh: service.refresh (failures reported, not raised).
        print(json.dumps({"at": datetime.now(timezone.utc), "refresh": refresh(jobs)}, default=str),
              flush=True)
        time.sleep(max(0.0, BUCKET.total_seconds() - (time.monotonic() - started)))


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="python -m worker", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bootstrap")
    b.add_argument("--dry-run", action="store_true")
    r = sub.add_parser("run")
    r.add_argument("job", choices=["segments", "traffic", "incidents", "events"])
    r.add_argument("--source", action="append", choices=SOURCES, help="traffic source (repeatable; default all)")
    r.add_argument("--no-geocode", action="store_true", help="incidents: never call a geocoding API")
    r.add_argument("--dry-run", action="store_true")
    sub.add_parser("schedule")
    bf = sub.add_parser("backfill")
    bf.add_argument("--date", required=True, type=date.fromisoformat, help="SF local day, YYYY-MM-DD")
    bf.add_argument("--dry-run", action="store_true")
    sv = sub.add_parser("serve", help="HTTP trigger for refreshes (POST /ingest/refresh, GET /ingest/status/<id>)")
    sv.add_argument("--host", default="127.0.0.1", help="bind address (default: localhost only)")
    sv.add_argument("--port", type=int, default=8100)
    args = p.parse_args(argv)

    load_dotenv(ENV_FILE)
    try:
        if args.cmd == "bootstrap":
            out = bootstrap(args.dry_run)
        elif args.cmd == "schedule":
            schedule()
            return 0
        elif args.cmd == "backfill":
            out = backfill(args.date, load_network() if GRAPHML.exists() else None, args.dry_run)
        elif args.cmd == "serve":
            from .server import serve
            serve(args.host, args.port)
            return 0
        elif args.job == "segments":
            out = run_segments(load_network(), args.dry_run)
        elif args.job == "events":
            out = run_events(args.dry_run)
        elif args.job == "incidents":
            net = load_network() if GRAPHML.exists() else None
            out = run_incidents(net, args.dry_run, use_geocoder=not args.no_geocode)
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
