"""Poll live feeds on their own schedules and append to time series.

    python -m pull.poll                  # all feeds whose keys are set, forever (Ctrl+C to stop)
    python -m pull.poll --once           # one round of each, e.g. from cron
    python -m pull.poll --only muni      # just one feed: mapbox | mapbox_tiles | tomtom | muni | events
    python -m pull.poll --every 300 --allow-paid

Feeds (each appends JSON lines to ingest/data/timeseries/<feed>/<UTC date>.jsonl):
- mapbox_corridors: live speed + congestion per road piece on our corridors (MAPBOX_TOKEN)
- muni_vehicles:    every Muni vehicle's position; speeds come from consecutive fixes (SF511_API_KEY)
- sf511_events:     Bay Area incidents/closures/construction, written when new or updated (SF511_API_KEY)
- tomtom_flow:      speed (km/h) + closure flag on every road line in SF, from TomTom's zoom-13
                    vector flow tiles (TOMTOM_API_KEY). "absolute" every 10 min; "relative"
                    (fraction of free-flow speed) every 6 h, so free-flow = absolute / relative.
- mapbox_traffic:   congestion level on every road line incl. residential streets, from
                    Mapbox's zoom-14 traffic tiles every 20 min (MAPBOX_TOKEN, separate tile quota).

This is raw history for the forecasting models; the ingestion worker will move it
into Tiger Data later.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from datasf.client import load_dotenv

from . import ENV_FILE, INGEST_DIR, feeds
from .corridors import CORRIDORS, Corridor, LonLat, requests_per_poll
from .http import FetchError, fetch

TS_ROOT = INGEST_DIR / "data" / "timeseries"
TS_DIR = TS_ROOT / "mapbox_corridors"
MUNI_DIR = TS_ROOT / "muni_vehicles"
EVENTS_DIR = TS_ROOT / "sf511_events"
TOMTOM_DIR = TS_ROOT / "tomtom_flow"
MAPBOX_TILES_DIR = TS_ROOT / "mapbox_traffic"

FREE_MONTHLY_REQUESTS = 100_000  # Mapbox Directions
BUDGET = 0.9 * FREE_MONTHLY_REQUESTS  # leave room for manual tests
SF511_HOURLY_LIMIT = 60  # per token
SF511_BUDGET = 55  # leave room for `python -m pull live` and manual tests
TOMTOM_FREE_MONTHLY_TILES = 200_000  # Traffic Flow & Incidents vector tiles
TOMTOM_BUDGET = 0.9 * TOMTOM_FREE_MONTHLY_TILES
TOMTOM_ZOOM = 13  # 25 tiles cover SF; already includes local roads
TOMTOM_TILE_URL = "https://api.tomtom.com/traffic/map/4/tile/flow/{style}/{z}/{x}/{y}.pbf"
MAPBOX_TILES_FREE_MONTHLY = 200_000  # Vector Tiles API, separate from Directions
MAPBOX_TILES_BUDGET = 0.9 * MAPBOX_TILES_FREE_MONTHLY
MAPBOX_TILES_ZOOM = 14  # 81 tiles; zoom 13 omits residential streets
MAPBOX_TILE_URL = "https://api.mapbox.com/v4/mapbox.mapbox-traffic-v1/{z}/{x}/{y}.mvt"
DIRECTIONS_URL = "https://api.mapbox.com/directions/v5/mapbox/driving-traffic/{coords}"
ANNOTATIONS = "distance,duration,speed,congestion,congestion_numeric,maxspeed"


def _append(directory: Path, when: datetime, rows: list[dict]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    with open(directory / f"{when:%Y-%m-%d}.jsonl", "a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


# --- Mapbox corridors ------------------------------------------------------

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
    rows = []
    for c in corridors:
        for direction, a, b in c.legs():
            row: dict[str, Any] = {"polled_at": polled_at.isoformat(timespec="seconds"),
                                   "corridor": c.key, "direction": direction}
            try:
                row.update(ok=True, **parse_route(fetch_route(a, b, token)))
            except (FetchError, ValueError, KeyError) as e:
                row.update(ok=False, error=str(e)[:300])
            rows.append(row)
    _append(TS_DIR, polled_at, rows)
    return sum(r["ok"] for r in rows), len(rows)


# --- Muni vehicles (511) ---------------------------------------------------

def muni_rows(activity: list[dict], polled_at: datetime) -> list[dict]:
    """One compact row per vehicle. 511 stamps every fix with the snapshot time, so
    speeds derived from consecutive fixes are accurate to about the poll interval."""
    rows = []
    for a in activity:
        j = a.get("MonitoredVehicleJourney") or {}
        loc = j.get("VehicleLocation") or {}
        try:
            lon, lat = float(loc["Longitude"]), float(loc["Latitude"])
        except (KeyError, TypeError, ValueError):
            continue
        rows.append({
            "polled_at": polled_at.isoformat(timespec="seconds"),
            "recorded_at": a.get("RecordedAtTime"),
            "vehicle": j.get("VehicleRef"),
            "line": j.get("LineRef"),  # None when out of service
            "direction": j.get("DirectionRef"),
            "lon": lon, "lat": lat,
            "bearing": float(j["Bearing"]) if j.get("Bearing") not in (None, "") else None,
            "occupancy": j.get("Occupancy"),
        })
    return rows


def poll_muni() -> tuple[int, int]:
    polled_at = datetime.now(timezone.utc)
    activity, _ = feeds.sf511_muni_vehicles()
    rows = muni_rows(activity, polled_at)
    _append(MUNI_DIR, polled_at, rows)
    return len(rows), len(activity)


# --- 511 traffic events ----------------------------------------------------

def event_fingerprint(e: dict) -> str:
    """Content hash ignoring `updated`, which 511 bumps every few minutes without changes."""
    body = {k: v for k, v in e.items() if k not in ("updated", "polled_at")}
    return hashlib.sha1(json.dumps(body, sort_keys=True).encode()).hexdigest()


class EventPoller:
    """Writes an event only when it's new or its content changed."""

    def __init__(self) -> None:
        # Remember what earlier runs already wrote, so a restart doesn't re-log every event.
        self.seen: dict[str, str] = {}
        for path in sorted(EVENTS_DIR.glob("*.jsonl")) if EVENTS_DIR.exists() else []:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    e = json.loads(line)
                    self.seen[e.get("id")] = event_fingerprint(e)

    def __call__(self) -> tuple[int, int]:
        polled_at = datetime.now(timezone.utc)
        events, _ = feeds.sf511_traffic_events()
        fresh = [e for e in events if self.seen.get(e.get("id")) != event_fingerprint(e)]
        for e in fresh:
            self.seen[e.get("id")] = event_fingerprint(e)
        _append(EVENTS_DIR, polled_at, [{"polled_at": polled_at.isoformat(timespec="seconds"), **e} for e in fresh])
        return len(fresh), len(events)


# --- traffic tiles (TomTom flow, Mapbox traffic) ----------------------------

class TilePoller:
    """One row per tile per poll: [line_key, value, road_class, closed] for each road line.
    Line geometry is written once to <dir>/geometry.jsonl (keyed by line_key), since tiles
    regroup lines into features as traffic changes. Subclasses say where tiles come from."""

    layer = ""
    directory: Path = TS_ROOT
    zoom = 13

    def __init__(self, style: str) -> None:
        from .tiles import tiles_for_bbox
        self.style = style
        self.tiles = tiles_for_bbox(z=self.zoom)
        self.empty: set[tuple[int, int, int]] = set()  # tiles with no roads (ocean); skipped after first 404
        self.geometry_file = self.directory / "geometry.jsonl"
        self.known: set[str] = set()
        if self.geometry_file.exists():
            self.known = {json.loads(l)["key"] for l in self.geometry_file.read_text(encoding="utf-8").splitlines() if l.strip()}

    def fetch_tile(self, z: int, x: int, y: int) -> bytes:
        raise NotImplementedError

    def line(self, key: str, props: dict) -> list:
        raise NotImplementedError

    def __call__(self) -> tuple[int, int]:
        from .tiles import decode_lines, line_key
        polled_at = datetime.now(timezone.utc)
        rows, new_geoms, ok = [], [], 0
        for z, x, y in self.tiles:
            if (z, x, y) in self.empty:
                continue
            row: dict[str, Any] = {"polled_at": polled_at.isoformat(timespec="seconds"), "style": self.style,
                                   "tile": [z, x, y]}
            try:
                lines = []
                for coords, props in decode_lines(self.fetch_tile(z, x, y), z, x, y, self.layer):
                    k = line_key(coords)
                    if k not in self.known:
                        self.known.add(k)
                        new_geoms.append({"key": k, **{f: props.get(f) for f in ("road_category", "road_subcategory",
                                                                                  "class", "structure") if f in props},
                                          "coords": coords})
                    lines.append(self.line(k, props))
                row.update(ok=True, lines=lines)
                ok += 1
            except FetchError as e:
                if str(e).startswith("404"):  # no roads in this tile
                    self.empty.add((z, x, y))
                    continue
                row.update(ok=False, error=f"FetchError: {str(e)[:200]}")
            except Exception as e:  # one bad tile shouldn't lose the rest of the round
                row.update(ok=False, error=f"{type(e).__name__}: {str(e)[:200]}")
            rows.append(row)
        if new_geoms:
            self.directory.mkdir(parents=True, exist_ok=True)
            with open(self.geometry_file, "a", encoding="utf-8") as f:
                f.writelines(json.dumps(g) + "\n" for g in new_geoms)
        _append(self.directory, polled_at, rows)
        return ok, len(rows)


class TomTomPoller(TilePoller):
    """TomTom flow: value = km/h ("absolute") or fraction of free-flow ("relative").
    More zoom adds nothing: TomTom's residential gaps are missing data, not detail."""

    layer, directory, zoom = "Traffic flow", TOMTOM_DIR, TOMTOM_ZOOM

    def __init__(self, key: str, style: str) -> None:
        self.key = key
        super().__init__(style)

    def fetch_tile(self, z: int, x: int, y: int) -> bytes:
        return fetch(TOMTOM_TILE_URL.format(style=self.style, z=z, x=x, y=y), params={
            "key": self.key, "tags": "[traffic_level,road_category,road_subcategory,road_closure]"}, timeout=30)

    def line(self, key: str, props: dict) -> list:
        return [key, props.get("traffic_level"), props.get("road_category"), bool(props.get("road_closure"))]


class MapboxTrafficPoller(TilePoller):
    """Mapbox traffic: value = congestion level (low/moderate/heavy/severe). Zoom 14 is
    where residential streets appear; this fills TomTom's residential gaps."""

    layer, directory, zoom = "traffic", MAPBOX_TILES_DIR, MAPBOX_TILES_ZOOM

    def __init__(self, token: str) -> None:
        self.token = token
        super().__init__("congestion")

    def fetch_tile(self, z: int, x: int, y: int) -> bytes:
        return fetch(MAPBOX_TILE_URL.format(z=z, x=x, y=y), params={"access_token": self.token}, timeout=30)

    def line(self, key: str, props: dict) -> list:
        return [key, props.get("congestion"), props.get("class"), bool(props.get("closed"))]


# --- scheduler -------------------------------------------------------------

class Feed:
    def __init__(self, name: str, every_s: float, run: Callable[[], tuple[int, int]], label: str = "ok"):
        self.name, self.every_s, self.run, self.label = name, every_s, run, label
        self.next_due = 0.0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="python -m pull.poll")
    p.add_argument("--every", type=float, default=600, help="Mapbox corridor interval, seconds (default 600)")
    p.add_argument("--muni-every", type=float, default=90, help="Muni vehicles interval, seconds (default 90)")
    p.add_argument("--events-every", type=float, default=600, help="511 events interval, seconds (default 600)")
    p.add_argument("--tomtom-every", type=float, default=600, help="TomTom absolute-speed tiles interval (default 600)")
    p.add_argument("--tomtom-relative-every", type=float, default=21600,
                   help="TomTom relative tiles interval (default 6 h; free-flow speed barely changes)")
    p.add_argument("--mapbox-tiles-every", type=float, default=1200, help="Mapbox traffic tiles interval (default 1200)")
    p.add_argument("--only", choices=["mapbox", "mapbox_tiles", "muni", "events", "tomtom"])
    p.add_argument("--once", action="store_true")
    p.add_argument("--allow-paid", action="store_true", help="allow Mapbox schedules over the free tier")
    args = p.parse_args(argv)

    load_dotenv(ENV_FILE)
    wanted = {args.only} if args.only else {"mapbox", "mapbox_tiles", "muni", "events", "tomtom"}
    active: list[Feed] = []

    if "mapbox" in wanted:
        token = os.environ.get("MAPBOX_TOKEN")
        if not token:
            print("mapbox: skipped, set MAPBOX_TOKEN in ingest/.env (https://account.mapbox.com/access-tokens/)")
        else:
            per_poll = requests_per_poll()
            projected = monthly_requests(args.every, per_poll)
            print(f"mapbox: {len(CORRIDORS)} corridors, {per_poll} requests/poll, every {args.every:.0f}s "
                  f"-> ~{projected:,.0f} requests/month (free tier {FREE_MONTHLY_REQUESTS:,})")
            if not args.once and projected > BUDGET and not args.allow_paid:
                print(f"over budget ({BUDGET:,.0f}); poll less often or pass --allow-paid")
                return 2
            active.append(Feed("mapbox_corridors", args.every, lambda: poll_once(token)))

    if "mapbox_tiles" in wanted and os.environ.get("MAPBOX_TOKEN"):
        from .tiles import tiles_for_bbox
        n = len(tiles_for_bbox(z=MAPBOX_TILES_ZOOM))
        monthly = monthly_requests(args.mapbox_tiles_every, n)
        print(f"mapbox tiles: {n} tiles/poll (zoom {MAPBOX_TILES_ZOOM}), every {args.mapbox_tiles_every:.0f}s "
              f"-> ~{monthly:,.0f} tiles/month (free {MAPBOX_TILES_FREE_MONTHLY:,})")
        if not args.once and monthly > MAPBOX_TILES_BUDGET:
            print(f"over Mapbox tiles budget ({MAPBOX_TILES_BUDGET:,.0f}); poll less often")
            return 2
        active.append(Feed("mapbox_traffic", args.mapbox_tiles_every,
                           MapboxTrafficPoller(os.environ["MAPBOX_TOKEN"]), label="tiles ok"))

    sf511 = [f for f in ("muni", "events") if f in wanted]
    if sf511 and not os.environ.get("SF511_API_KEY"):
        print("511: skipped, set SF511_API_KEY in ingest/.env (https://511.org/open-data/token)")
    elif sf511:
        hourly = (3600 / args.muni_every if "muni" in sf511 else 0) + (3600 / args.events_every if "events" in sf511 else 0)
        print(f"511: ~{hourly:.0f} requests/hour (token limit {SF511_HOURLY_LIMIT}/hour)")
        if not args.once and hourly > SF511_BUDGET:
            print(f"over 511 budget ({SF511_BUDGET}/hour); poll less often")
            return 2
        if "muni" in sf511:
            active.append(Feed("muni_vehicles", args.muni_every, poll_muni))
        if "events" in sf511:
            active.append(Feed("sf511_events", args.events_every, EventPoller(), label="new/updated"))

    if "tomtom" in wanted:
        tt_key = os.environ.get("TOMTOM_API_KEY")
        if not tt_key:
            print("tomtom: skipped, set TOMTOM_API_KEY in ingest/.env (https://developer.tomtom.com)")
        else:
            from .tiles import tiles_for_bbox
            n = len(tiles_for_bbox(z=TOMTOM_ZOOM))
            monthly = monthly_requests(args.tomtom_every, n) + monthly_requests(args.tomtom_relative_every, n)
            print(f"tomtom: {n} tiles/poll, absolute every {args.tomtom_every:.0f}s + relative every "
                  f"{args.tomtom_relative_every:.0f}s -> ~{monthly:,.0f} tiles/month (free {TOMTOM_FREE_MONTHLY_TILES:,})")
            if not args.once and monthly > TOMTOM_BUDGET:
                print(f"over TomTom budget ({TOMTOM_BUDGET:,.0f}); poll less often")
                return 2
            active.append(Feed("tomtom_absolute", args.tomtom_every, TomTomPoller(tt_key, "absolute"), label="tiles ok"))
            active.append(Feed("tomtom_relative", args.tomtom_relative_every, TomTomPoller(tt_key, "relative"), label="tiles ok"))

    if not active:
        return 2
    failures = 0
    while True:
        now = time.monotonic()
        for feed in active:
            if now < feed.next_due:
                continue
            feed.next_due = now + feed.every_s
            try:
                ok, total = feed.run()
                note = f"{ok}/{total} {feed.label}"
                failures += ok < total and feed.name == "mapbox_corridors"
            except Exception as e:  # keep the other feeds running
                note = f"FAILED: {type(e).__name__}: {str(e)[:150]}"
                failures += 1
            print(f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%SZ}  {feed.name:<17} {note}", flush=True)
        if args.once:
            return 1 if failures else 0
        time.sleep(max(1.0, min(f.next_due for f in active) - time.monotonic()))


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(0)
