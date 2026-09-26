"""Live connectivity + freshness check for DataSF.

    python -m datasf            # check every dataset, then show active closures
    python -m datasf sample street_closures 3   # dump raw rows as JSON
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone

from . import DATASETS, DataSF, DataSFError, active_street_closures, latest
from .datasets import SF_TZ, parse_ts


def _age(dt: datetime | None, now: datetime) -> str:
    if dt is None:
        return "-"
    hours = (now - dt).total_seconds() / 3600
    return f"{hours:.1f}h ago" if hours < 48 else f"{hours / 24:.0f}d ago"


def check(client: DataSF) -> int:
    now = datetime.now(timezone.utc)
    print(f"DataSF {client.base_url}  app token: {'yes' if client.app_token else 'no (IP-throttled)'}\n")
    print(f"{'dataset':<20} {'id':<10} {'portal refreshed':<17} {'newest record':<17} ")
    failures = 0
    for ds in DATASETS.values():
        try:
            meta = client.metadata(ds.id)
            refreshed = datetime.fromtimestamp(meta["rowsUpdatedAt"], timezone.utc) if meta.get("rowsUpdatedAt") else None
            if ds.time_field:
                rows = latest(client, ds)
                newest = _age(parse_ts(rows[0].get(ds.time_field), is_utc=ds.time_is_utc) if rows else None, now)
            else:
                newest = "(static)"
            print(f"{ds.key:<20} {ds.id:<10} {_age(refreshed, now):<17} {newest:<17}")
        except DataSFError as e:
            failures += 1
            print(f"{ds.key:<20} {ds.id:<10} FAILED: {e}")

    try:
        closures = active_street_closures(client)
    except DataSFError as e:
        print(f"\nactive street closures: FAILED: {e}")
        return 1
    print(f"\nactive street closures right now: {len(closures)}")
    for kind, n in Counter(c.get("type") for c in closures).most_common():
        print(f"  {n:>4}  {kind}")
    for c in [c for c in closures if c.get("type") == "Special Event"][:5]:
        end = parse_ts(c.get("end_utc"), is_utc=True)
        until = f"  until {end.astimezone(SF_TZ):%a %H:%M}" if end else ""
        print(f"  - {c.get('case_name', '?')[:40]:<40} {c.get('street')} ({c.get('from_st')} -> {c.get('to_st')}){until}")
    return 1 if failures else 0


def sample(client: DataSF, key: str, n: int) -> int:
    print(json.dumps(latest(client, DATASETS[key], n), indent=2))
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    client = DataSF()
    if args[:1] == ["sample"] and len(args) >= 2 and args[1] in DATASETS:
        sys.exit(sample(client, args[1], int(args[2]) if len(args) > 2 else 3))
    if args:
        sys.exit(f"usage: python -m datasf [sample <{'|'.join(DATASETS)}> [n]]")
    sys.exit(check(client))
