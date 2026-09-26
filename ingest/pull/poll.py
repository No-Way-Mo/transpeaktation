"""Poll live speed/congestion on our corridors and append to a time series.

    python -m pull.poll            # every 10 min, forever (Ctrl+C to stop)
    python -m pull.poll --once     # one round, e.g. from cron
    python -m pull.poll --every 300 --allow-paid

Each request appends one JSON line to ingest/data/timeseries/mapbox_corridors/<UTC date>.jsonl.
This is raw history for the forecasting models; the ingestion worker will move it
into Tiger Data later.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

from datasf.client import load_dotenv

from . import ENV_FILE, INGEST_DIR
from .corridors import CORRIDORS, Corridor, LonLat, requests_per_poll
from .http import FetchError, fetch

TS_DIR = INGEST_DIR / "data" / "timeseries" / "mapbox_corridors"
FREE_MONTHLY_REQUESTS = 100_000
BUDGET = 0.9 * FREE_MONTHLY_REQUESTS  # leave room for manual tests
DIRECTIONS_URL = "https://api.mapbox.com/directions/v5/mapbox/driving-traffic/{coords}"
ANNOTATIONS = "distance,duration,speed,congestion,congestion_numeric,maxspeed"


def monthly_requests(every_s: float, per_poll: int) -> float:
    return per_poll * 30 * 86_400 / every_s


def fetch_route(a: LonLat, b: LonLat, token: str) -> dict[str, Any]:
    coords = f"{a[0]},{a[1]};{b[0]},{b[1]}"
    body = fetch(DIRECTIONS_URL.format(coords=coords), params={
        "access_token": token, "annotations": ANNOTATIONS, "geometries": "geojson",
        "overview": "full", "alternatives": "false"}, timeout=30, retries=2,
        # Mapbox intermittently 401s a valid token while it propagates to all its servers.
        retry_on=frozenset({401}))
    return json.loads(body)


def parse_route(resp: dict[str, Any]) -> dict[str, Any]:
    """Keep what the forecasting side needs from a Directions response.
    Units as Mapbox returns them: seconds, metres, metres/second."""
    if resp.get("code") != "Ok" or not resp.get("routes"):
        raise ValueError(f"no route: {resp.get('code')} {resp.get('message', '')}".strip())
    route = resp["routes"][0]
    ann = route["legs"][0].get("annotation", {})
    return {
        "duration_s": route.get("duration"),
        "duration_typical_s": route.get("duration_typical"),  # same trip without live traffic
        "distance_m": route.get("distance"),
        "segments": {
            "distance_m": ann.get("distance"),
            "duration_s": ann.get("duration"),
            "speed_mps": ann.get("speed"),
            "congestion": ann.get("congestion"),
            "congestion_numeric": ann.get("congestion_numeric"),
            "maxspeed": ann.get("maxspeed"),
        },
        "geometry": route.get("geometry", {}).get("coordinates"),
    }


def poll_once(token: str, corridors: list[Corridor] = CORRIDORS) -> tuple[int, int]:
    polled_at = datetime.now(timezone.utc)
    TS_DIR.mkdir(parents=True, exist_ok=True)
    ok = 0
    rows = []
    for c in corridors:
        for direction, a, b in c.legs():
            row: dict[str, Any] = {"polled_at": polled_at.isoformat(timespec="seconds"),
                                   "corridor": c.key, "direction": direction}
            try:
                row.update(ok=True, **parse_route(fetch_route(a, b, token)))
                ok += 1
            except (FetchError, ValueError, KeyError) as e:
                row.update(ok=False, error=str(e)[:300])
            rows.append(row)
    with open(TS_DIR / f"{polled_at:%Y-%m-%d}.jsonl", "a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    return ok, len(rows)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="python -m pull.poll")
    p.add_argument("--every", type=float, default=600, help="seconds between polls (default 600)")
    p.add_argument("--once", action="store_true")
    p.add_argument("--allow-paid", action="store_true", help="allow schedules over the free tier")
    args = p.parse_args(argv)

    load_dotenv(ENV_FILE)
    token = os.environ.get("MAPBOX_TOKEN")
    if not token:
        print("set MAPBOX_TOKEN in ingest/.env (https://account.mapbox.com/access-tokens/)")
        return 2
    per_poll = requests_per_poll()
    projected = monthly_requests(args.every, per_poll)
    print(f"{len(CORRIDORS)} corridors, {per_poll} requests/poll, every {args.every:.0f}s "
          f"-> ~{projected:,.0f} requests/month (free tier {FREE_MONTHLY_REQUESTS:,})")
    if not args.once and projected > BUDGET and not args.allow_paid:
        print(f"over budget ({BUDGET:,.0f}); poll less often or pass --allow-paid")
        return 2

    while True:
        started = time.monotonic()
        ok, total = poll_once(token)
        print(f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%SZ}  {ok}/{total} routes ok", flush=True)
        if args.once:
            return 0 if ok == total else 1
        time.sleep(max(0.0, args.every - (time.monotonic() - started)))


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(0)
