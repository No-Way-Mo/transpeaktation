"""Normalize the raw snapshots from `python -m pull` and write them to MongoDB / Tiger Data.

    python -m worker                    # every source
    python -m worker live               # one layer: static | planned | live
    python -m worker streets chp_incidents
    python -m worker mapbox_corridors   # Mapbox speed polls -> Tiger traffic_metrics
    python -m worker --dry-run          # whole pipeline, no DB writes; dumps data/normalized/
    python -m worker --no-geocode --dump --log-format text

Exit code 1 if a source failed, a write failed, or a needed store was unavailable.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from datasf.client import load_dotenv
from pull import DATA_DIR, ENV_FILE

from . import geocode, log
from .pipeline import INGEST_DATA, Pipeline, RunResult, open_writers, select
from .adapters import TIMESERIES
from .storage import MONGO_INDEXES


def print_summary(res: RunResult) -> None:
    cols = ("status", "raw", "normalized", "filtered", "rejected", "duplicates", "merged", "from_cnn", "snapped",
            "linked", "geocoded", "stored", "unrouted", "mongo_new", "mongo_updated", "tiger_rows", "write_errors")
    short = {"normalized": "norm", "filtered": "filt", "rejected": "rej", "duplicates": "dup", "merged": "merge",
             "from_cnn": "cnn", "snapped": "snap", "geocoded": "geo", "mongo_new": "m_new",
             "mongo_updated": "m_upd", "tiger_rows": "tiger", "write_errors": "w_err", "linked": "link",
             "unrouted": "unrt"}
    print(f"\n{'source':<24} " + " ".join(f"{short.get(c, c):>11}" if c == "status" else f"{short.get(c, c):>6}"
                                         for c in cols))
    for st in res.stats.values():
        vals = [f"{st.status:>11}"] + [f"{getattr(st, c):>6}" for c in cols[1:]]
        print(f"{st.source:<24} " + " ".join(vals))
    notes = [f"{s.source}: {s.note}" for s in res.stats.values() if s.note] + res.notes
    if notes:
        print("\nnotes:")
        for n in notes:
            print(f"  - {n}")
    if res.dry_run:
        done = "DRY RUN: nothing written to MongoDB / Tiger Data"
    else:
        st = res.stats.values()
        done = (f"MongoDB {sum(s.mongo_new for s in st)} new + {sum(s.mongo_updated for s in st)} updated, "
                f"Tiger Data {sum(s.tiger_rows for s in st)} rows (+{sum(s.tiger_skipped for s in st)} already stored)")
    print(f"\n{len(res.records)} records normalized; {done}; exit {res.exit_code}")


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="python -m worker", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("targets", nargs="*", help="layers (static|planned|live) and/or source names; default: all")
    p.add_argument("--dry-run", action="store_true", help="run everything except DB writes (implies --dump)")
    p.add_argument("--dump", action="store_true", help="also write data/normalized/<source>.json")
    p.add_argument("--no-geocode", action="store_true", help="never call a geocoding API")
    p.add_argument("--raw-dir", type=Path, default=DATA_DIR, help="snapshot dir (default: ingest/data/raw)")
    p.add_argument("--timeseries-dir", type=Path, default=None,
                   help="Mapbox poll dir (default: ingest/data/timeseries/mapbox_corridors)")
    p.add_argument("--out-dir", type=Path, default=INGEST_DATA,
                   help="where normalized/ and quarantine/ go (default: ingest/data)")
    p.add_argument("--ensure-indexes", action="store_true", help="create indexes on the worker's Mongo collections")
    p.add_argument("--log-format", choices=("json", "text"), default="json")
    args = p.parse_args(argv)

    load_dotenv(ENV_FILE)
    log.setup(args.log_format)
    try:
        names = select(args.targets)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2

    geocoder, why = (None, "geocoding disabled (--no-geocode)") if args.no_geocode else \
        geocode.from_env(args.out_dir / "cache" / "geocode.json")
    log.event("geocoder", provider=getattr(geocoder, "name", None), detail=why)

    mongo, tiger, store_errors = open_writers(args.dry_run)
    for store, err in store_errors.items():
        log.event("store_unavailable", logging.WARNING, store=store, reason=err)
    if args.ensure_indexes and mongo:
        mongo.ensure_indexes(MONGO_INDEXES)
    try:
        res = Pipeline(args.raw_dir, out_dir=args.out_dir, dry_run=args.dry_run, dump=args.dump,
                       geocoder=geocoder, mongo=mongo, tiger=tiger, store_errors=store_errors,
                       timeseries_dirs={n: args.timeseries_dir for n in TIMESERIES} if args.timeseries_dir else None
                       ).run(names)
    finally:
        for w in (mongo, tiger):
            if w is not None:
                w.close()
    if geocoder is None:
        res.notes.append(why)
    print_summary(res)
    return res.exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
