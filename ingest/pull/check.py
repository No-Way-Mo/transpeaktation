"""Data-quality report on the raw snapshots in ingest/data/raw/.

    python -m pull.check

Checks: non-empty, unique ids, geometry present and inside SF, timestamps parse,
freshness for live feeds, and whether each record joins to the SF street network
(cnn). Exit code 1 if anything FAILs; WARNs are worth reading but not blocking.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable

from datasf import DATASETS
from datasf.datasets import SF_TZ, parse_ts

from . import DATA_DIR, MANIFEST
from .feeds import SF_BBOX
from .sources import SOURCES

BAY_BBOX = (-123.7, 36.8, -121.2, 38.9)  # Caltrans District 4 / CHP Golden Gate
PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


@dataclass
class Finding:
    level: str
    check: str
    detail: str


# --- helpers ---------------------------------------------------------------

def coords(value: Any) -> list[tuple[float, float]]:
    """(lon, lat) pairs from a GeoJSON geometry or a Socrata location dict."""
    if isinstance(value, dict):
        if "coordinates" in value:
            return list(_walk(value["coordinates"]))
        if value.get("latitude") not in (None, "") and value.get("longitude") not in (None, ""):
            return [(float(value["longitude"]), float(value["latitude"]))]
    return []


def _walk(c: Any) -> Iterable[tuple[float, float]]:
    if isinstance(c, list) and len(c) >= 2 and all(isinstance(x, (int, float)) for x in c[:2]):
        yield float(c[0]), float(c[1])
    elif isinstance(c, list):
        for part in c:
            yield from _walk(part)


def inside(pt: tuple[float, float], bbox: tuple[float, float, float, float]) -> bool:
    lon, lat = pt
    return bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]


def pct(n: int, d: int) -> str:
    return f"{100 * n / d:.1f}%" if d else "n/a"


def cnn_key(v: Any) -> str | None:
    try:
        return str(int(float(v)))
    except (TypeError, ValueError):
        return None


def age(dt: datetime, now: datetime) -> str:
    mins = (now - dt).total_seconds() / 60
    return f"{mins:.0f} min" if mins < 120 else f"{mins / 60:.1f} h"


def freshness(newest: datetime | None, now: datetime, warn: timedelta, fail: timedelta, what: str) -> Finding:
    if newest is None:
        return Finding(FAIL, "freshness", f"no parseable {what}")
    lag = now - newest
    level = FAIL if lag > fail else WARN if lag > warn else PASS
    return Finding(level, "freshness", f"newest {what} {age(newest, now)} old")


def geo_findings(rows: list[dict], get: Callable[[dict], list[tuple[float, float]]],
                 bbox: tuple, area: str, label: str = "rows") -> list[Finding]:
    if not rows:
        return [Finding(WARN, "geometry", f"no {label} to check")]
    pts = [get(r) for r in rows]
    have = [p for p in pts if p]
    out = sum(1 for p in have if not all(inside(c, bbox) for c in p))
    share = len(have) / len(rows)
    level = PASS if share >= 0.95 else WARN if share >= 0.5 else FAIL
    found = [Finding(level, "geometry", f"{pct(len(have), len(rows))} of {label} have coordinates")]
    if have:
        found.append(Finding(WARN if out / len(have) > 0.01 else PASS, "in-area",
                             f"{pct(len(have) - out, len(have))} of geometries inside {area}"))
    return found


# --- DataSF ----------------------------------------------------------------

def check_datasf(key: str, rows: list[dict], ctx: dict) -> list[Finding]:
    ds = DATASETS[key]
    now = ctx["now"]
    found = []
    if ds.id_field:
        fields = (ds.id_field,) if isinstance(ds.id_field, str) else ds.id_field
        ids = [tuple(r.get(f) for f in fields) for r in rows]
        missing = sum(1 for i in ids if any(v in (None, "") for v in i))
        dupes = sum(n - 1 for n in Counter(ids).values() if n > 1)
        found.append(Finding(PASS if not (missing or dupes) else WARN, "unique ids",
                             f"{'+'.join(fields)}: {missing} missing, {dupes} duplicates"))
    if ds.geo_field:
        scope, label = GEO_SCOPE.get(key, (lambda r: True, "rows"))
        found += geo_findings([r for r in rows if scope(r)], lambda r: coords(r.get(ds.geo_field)),
                              SF_BBOX, "SF", label)
    if ds.time_field:
        bad = sum(1 for r in rows if r.get(ds.time_field) and _parse_or_none(r[ds.time_field], ds.time_is_utc) is None)
        empty = sum(1 for r in rows if not r.get(ds.time_field))
        found.append(Finding(PASS if not bad else WARN, "timestamps",
                             f"{ds.time_field}: {bad} unparseable, {empty} empty"))
    if any("cnn" in r for r in rows[:500]) and key != "streets" and ctx["street_cnns"]:
        # A cnn names either a street segment or an intersection (node); both join.
        cnns = {c for c in (cnn_key(r.get("cnn")) for r in rows) if c}
        seg = cnns & ctx["street_cnns"]
        node = (cnns - seg) & ctx["node_cnns"]
        hit = len(seg) + len(node)
        rows_with = sum(1 for r in rows if cnn_key(r.get("cnn")))
        found.append(Finding(PASS if hit >= 0.95 * len(cnns) else WARN, "joins streets",
                             f"{pct(rows_with, len(rows))} of rows have a cnn; {pct(hit, len(cnns))} of "
                             f"{len(cnns)} distinct cnns join ({len(seg)} segments, {len(node)} intersections)"))
    found += EXTRA.get(key, lambda rows, ctx: [])(rows, ctx)
    return found


def _parse_or_none(value: str, is_utc: bool) -> datetime | None:
    try:
        return parse_ts(value, is_utc=is_utc)
    except ValueError:
        return None


def _streets(rows, ctx):
    ow = Counter(r.get("oneway") for r in rows)
    return [Finding(PASS, "one-way flags", f"B(both)={ow['B']} F={ow['F']} T={ow['T']} missing={ow[None]}")]


FREEWAY_SENTINEL = 99  # SFMTA uses 99 on state freeways/ramps (US-101, I-280), which it doesn't set


def _speed_limit(r: dict) -> int:
    return int(float(r.get("speedlimit") or 0))


def _speed_limits(rows, ctx):
    limits = [_speed_limit(r) for r in rows]
    posted = [x for x in limits if 0 < x != FREEWAY_SENTINEL]
    odd = sorted({x for x in posted if x % 5 or x > 65})
    found = [Finding(PASS if not odd else WARN, "values",
                     f"{pct(len(posted), len(rows))} posted; mph counts {sorted(Counter(posted).items())}; "
                     f"{limits.count(FREEWAY_SENTINEL)} freeway segments marked 99 (state-managed); "
                     f"{limits.count(0)} unposted (CA default 25)" + (f"; odd values {odd}" if odd else ""))]
    if ctx["street_cnns"]:
        covered = {cnn_key(r.get("cnn")) for r in rows if 0 < _speed_limit(r) != FREEWAY_SENTINEL}
        found.append(Finding(PASS, "street coverage",
                             f"{pct(len(covered & ctx['street_cnns']), len(ctx['street_cnns']))} of active street "
                             "segments have a posted limit"))
    return found


def _closures(rows, ctx):
    now = ctx["now"]
    spans = [(parse_ts(r.get("start_utc"), is_utc=True), parse_ts(r.get("end_utc"), is_utc=True)) for r in rows]
    inverted = sum(1 for s, e in spans if s and e and e < s)
    active = [r for r, (s, e) in zip(rows, spans) if s and e and s <= now <= e]
    events = [r for r in rows if r.get("type") == "Special Event"]
    return [
        Finding(PASS if not inverted else WARN, "time spans", f"{inverted} end-before-start"),
        Finding(PASS if active else WARN, "active now",
                f"{len(active)} in effect now ({dict(Counter(r.get('type') for r in active))}); "
                f"{len(events)} special-event closures now or upcoming"),
        Finding(PASS, "status", str(dict(Counter(r.get("status") for r in rows).most_common(6)))),
    ]


def _span_check(start: str, end: str):
    def check(rows, ctx):
        spans = [(_parse_or_none(r[start], False) if r.get(start) else None,
                  _parse_or_none(r[end], False) if r.get(end) else None) for r in rows]
        inverted = sum(1 for s, e in spans if s and e and e < s)
        active = sum(1 for s, e in spans if s and e and s <= ctx["now"] <= e)
        return [Finding(PASS if not inverted else WARN, "time spans",
                        f"{inverted} end-before-start; {active} active now")]
    return check


def _parking_signs(rows, ctx):
    today = ctx["now"].astimezone(SF_TZ).date()
    bad = active = 0
    for r in rows:
        try:
            s = datetime.strptime(r["startdate"], "%m/%d/%Y").date()
            e = datetime.strptime(r["enddate"], "%m/%d/%Y").date()
        except (KeyError, TypeError, ValueError):
            bad += 1
            continue
        active += s <= today <= e
    return [Finding(PASS if not bad else WARN, "sign dates", f"{bad} unparseable; {active} posted today")]


def _police_dispatch(rows, ctx):
    now = ctx["now"]
    times = [t for t in (_parse_or_none(r.get("received_datetime") or "", False) for r in rows) if t]
    f = freshness(max(times, default=None), now, timedelta(hours=1), timedelta(hours=6), "call")
    recent = sum(now - t <= timedelta(hours=48) for t in times)
    f.detail += f"; {recent} calls from the last 48 h, {len(times) - recent} older (long-open calls)"
    hidden = sum(1 for r in rows if r.get("sensitive_call") and not r.get("intersection_point"))
    return [f, Finding(PASS, "withheld", f"{hidden} sensitive calls have no location by design"),
            Finding(PASS, "call types",
                       str(Counter(r.get("call_type_final_desc") or r.get("call_type_original_desc")
                                   for r in rows).most_common(6)))]


# Which rows are expected to carry geometry (and what to call them in the report).
GEO_SCOPE: dict[str, tuple[Callable[[dict], bool], str]] = {
    "police_dispatch": (lambda r: not r.get("sensitive_call"), "non-sensitive calls"),
}

EXTRA: dict[str, Callable[[list[dict], dict], list[Finding]]] = {
    "streets": _streets,
    "speed_limits": _speed_limits,
    "street_closures": _closures,
    "street_use_permits": _span_check("permit_start_date", "permit_end_date"),
    "excavation_permits": _span_check("effective_date", "expiration_date"),
    "parking_signs": _parking_signs,
    "police_dispatch": _police_dispatch,
}


# --- other feeds -----------------------------------------------------------

def check_caltrans(rows, snap, ctx):
    now_epoch = ctx["now"].timestamp()

    def begin(r):
        b = r.get("location", {}).get("begin", {})
        try:
            return [(float(b["beginLongitude"]), float(b["beginLatitude"]))]
        except (KeyError, TypeError, ValueError):
            return []

    def epoch(r, field):
        try:
            return float(r["closure"]["closureTimestamp"][field])
        except (KeyError, TypeError, ValueError):
            return None

    sf = [r for r in rows if r.get("location", {}).get("begin", {}).get("beginCounty") == "San Francisco"]
    active = [r for r in rows if (epoch(r, "closureStartEpoch") or 1e18) <= now_epoch <= (epoch(r, "closureEndEpoch") or 0)]
    no_times = sum(1 for r in rows if epoch(r, "closureStartEpoch") is None)
    return geo_findings(rows, begin, BAY_BBOX, "the Bay Area") + [
        Finding(PASS if not no_times else WARN, "closure times", f"{no_times} rows without a start time"),
        Finding(PASS if sf else WARN, "SF coverage",
                f"{len(sf)} closures in SF county; {len(active)} Bay Area closures active now"),
    ]


def chp_time(r: dict) -> datetime | None:
    try:
        return datetime.strptime(" ".join(r["LogTime"].split()), "%b %d %Y %I:%M%p").replace(tzinfo=SF_TZ)
    except (KeyError, ValueError):
        return None


def chp_point(r: dict) -> list[tuple[float, float]]:
    m = re.fullmatch(r"(\d+):(\d+)", r.get("LATLON", ""))
    if not m or m.group(1) == "0":
        return []
    return [(-int(m.group(2)) / 1e6, int(m.group(1)) / 1e6)]


def check_chp(rows, snap, ctx):
    bay = [r for r in rows if r.get("center") == "GGCC" or r.get("dispatch") == "GGCC"]
    complete = snap["meta"].get("complete_xml")
    found = [
        Finding(PASS if complete else WARN, "feed integrity",
                "XML complete" if complete else f"XML served truncated at {snap['meta'].get('bytes')} bytes; "
                                                 "tail entries lost, rest parsed entry by entry"),
        freshness(max(filter(None, map(chp_time, rows)), default=None), ctx["now"],
                  timedelta(hours=1), timedelta(hours=6), "incident"),
        Finding(PASS if bay else WARN, "Bay Area coverage", f"{len(bay)} incidents from Golden Gate dispatch (GGCC)"),
    ]
    located = [r for r in rows if chp_point(r)]
    unlocated = Counter(r.get("LogType") for r in rows if not chp_point(r))
    found.append(Finding(PASS, "no location",
                         f"{sum(unlocated.values())} incidents given as 0:0 ({dict(unlocated.most_common(3))})"))
    return found + geo_findings(located, chp_point, (-124.5, 32.5, -114.0, 42.1), "California", "located incidents")


def check_osm_graph(rows, snap, ctx):
    meta = snap["meta"]
    maxspeed = sum(1 for r in rows if r.get("maxspeed"))
    oneway = sum(1 for r in rows if r.get("oneway") in (True, "True", "true"))
    unnamed = sum(1 for r in rows if not r.get("name"))
    hw = Counter(r["highway"] if isinstance(r.get("highway"), str) else "mixed" for r in rows)
    return [
        Finding(PASS if meta.get("nodes", 0) > 5000 else FAIL, "size",
                f"{meta.get('nodes')} intersections, {meta.get('edges')} directed road edges"),
        Finding(PASS, "attributes", f"maxspeed on {pct(maxspeed, len(rows))}; one-way {pct(oneway, len(rows))}; "
                                    f"unnamed {pct(unnamed, len(rows))}"),
        Finding(PASS, "road classes", str(hw.most_common(6))),
    ]


def check_turns(rows, snap, ctx):
    kinds = Counter(r.get("tags", {}).get("restriction", "(conditional/other)") for r in rows)
    complete = sum(1 for r in rows if {m.get("role") for m in r.get("members", [])} >= {"from", "to", "via"})
    return [Finding(PASS if complete >= 0.95 * len(rows) else WARN, "members",
                    f"{pct(complete, len(rows))} have from/via/to members"),
            Finding(PASS, "kinds", str(kinds.most_common(6)))]


def check_511(rows, snap, ctx):
    return [Finding(PASS, "sample keys", ", ".join(sorted(rows[0])[:12]))]


OTHER: dict[str, Callable[[list[dict], dict, dict], list[Finding]]] = {
    "caltrans_lane_closures": check_caltrans,
    "chp_incidents": check_chp,
    "osm_drive_graph": check_osm_graph,
    "osm_turn_restrictions": check_turns,
    "sf511_traffic_events": check_511,
    "sf511_muni_vehicles": check_511,
}


# --- runner ----------------------------------------------------------------

def load(name: str) -> dict | None:
    path = DATA_DIR / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def run() -> int:
    now = datetime.now(timezone.utc)
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    streets = load("streets")
    street_rows = streets["records"] if streets else []
    ctx = {"now": now,
           "street_cnns": {c for c in (cnn_key(r.get("cnn")) for r in street_rows) if c},
           "node_cnns": {c for r in street_rows
                         for c in (cnn_key(r.get("f_node_cnn")), cnn_key(r.get("t_node_cnn"))) if c}}
    fails = warns = 0
    for name, src in SOURCES.items():
        entry = manifest.get(name, {})
        snap = load(name)
        if entry.get("status") == "skip":
            print(f"\n{name} [{src.layer}]  SKIPPED: {entry.get('reason')}")
            continue
        if entry.get("status") == "fail" or snap is None:
            fails += 1
            print(f"\n{name} [{src.layer}]  FAIL: {entry.get('error', 'not pulled yet (python -m pull)')}")
            continue
        rows = snap["records"]
        pulled = datetime.fromisoformat(snap["pulled_at"])
        print(f"\n{name} [{src.layer}]  {len(rows)} rows, pulled {age(pulled, now)} ago")
        if not rows:
            findings = [Finding(FAIL, "non-empty", "0 rows")]
        elif name in DATASETS:
            findings = check_datasf(name, rows, ctx)
        else:
            findings = OTHER[name](rows, snap, ctx)
        for f in findings:
            fails += f.level == FAIL
            warns += f.level == WARN
            print(f"  {f.level}  {f.check:<16} {f.detail}")
    print(f"\n{fails} FAIL, {warns} WARN")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(run())
