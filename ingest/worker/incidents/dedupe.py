"""Deduplication.

Within a source: records share a deterministic id (source + natural key); keep the first.

Across sources (conservative, deterministic; incidents and closures only): two records
from *different* sources merge only when ALL of these hold:
  incidents: same category (not 'other'), located, <= 200 m apart, reported <= 30 min apart
  closures:  located, <= 100 m apart, time windows overlap, and street-text Jaccard >= 0.5
The kept record is chosen by SOURCE_PRIORITY, then id; it gains `also_reported_by`,
the others are dropped from persistence (their provenance survives on the kept record).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

from .common import location_tokens
from .geom import min_distance_m
from .records import Record

INCIDENT_RADIUS_M = 200
INCIDENT_WINDOW = timedelta(minutes=30)
CLOSURE_RADIUS_M = 100
CLOSURE_TEXT_JACCARD = 0.5

# Lower index wins. Authoritative feeds first.
SOURCE_PRIORITY = ["chp_incidents", "caltrans_lane_closures", "street_closures", "sf511_traffic_events",
                   "police_dispatch"]
CROSS_SOURCE_KINDS = ("incident", "closure")
CROSS_SOURCE_CLOSURES = {"street_closures", "caltrans_lane_closures", "sf511_traffic_events"}


def within_source(records: Iterable[Record]) -> tuple[list[Record], int]:
    seen: dict[str, Record] = {}
    dupes = 0
    for r in records:
        if r.id in seen:
            dupes += 1
        else:
            seen[r.id] = r
    return list(seen.values()), dupes


def _priority(r: Record) -> tuple[int, str]:
    rank = SOURCE_PRIORITY.index(r.source) if r.source in SOURCE_PRIORITY else len(SOURCE_PRIORITY)
    return rank, r.id


def _text(r: Record) -> frozenset[str]:
    a = r.attributes
    return location_tokens(a.get("location_text"), a.get("street"), a.get("from_street"), a.get("to_street"),
                           a.get("route"), a.get("end_location_text"))


def _jaccard(a: frozenset, b: frozenset) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


_MIN = datetime.min.replace(tzinfo=timezone.utc)
_MAX = datetime.max.replace(tzinfo=timezone.utc)


def _overlap(a: Record, b: Record) -> bool:
    """Time windows overlap; an open start/end counts as unbounded, but each needs one bound."""
    if not (a.valid_from or a.valid_to) or not (b.valid_from or b.valid_to):
        return False
    return max(a.valid_from or _MIN, b.valid_from or _MIN) <= min(a.valid_to or _MAX, b.valid_to or _MAX)


def is_same(a: Record, b: Record) -> bool:
    if a.source == b.source or a.kind != b.kind or a.kind not in CROSS_SOURCE_KINDS:
        return False
    if a.geometry is None or b.geometry is None:
        return False
    if a.kind == "incident":
        cat = a.attributes.get("category")
        if cat in (None, "other") or cat != b.attributes.get("category"):
            return False
        if not a.observed_at or not b.observed_at or abs(a.observed_at - b.observed_at) > INCIDENT_WINDOW:
            return False
        d = min_distance_m(a.geometry, b.geometry)
        return d is not None and d <= INCIDENT_RADIUS_M
    # closures
    if a.source not in CROSS_SOURCE_CLOSURES or b.source not in CROSS_SOURCE_CLOSURES:
        return False
    if not _overlap(a, b) or _jaccard(_text(a), _text(b)) < CLOSURE_TEXT_JACCARD:
        return False
    d = min_distance_m(a.geometry, b.geometry)
    return d is not None and d <= CLOSURE_RADIUS_M


def _pairs(candidates: list[Record]):
    """Candidate pairs in a deterministic order. Incidents are compared only within the
    time window (sorted sweep), so thousands of police calls stay cheap."""
    incidents = sorted((r for r in candidates if r.kind == "incident" and r.observed_at),
                       key=lambda r: (r.observed_at, _priority(r)))
    for i, a in enumerate(incidents):
        for b in incidents[i + 1:]:
            if b.observed_at - a.observed_at > INCIDENT_WINDOW:
                break
            yield (a, b) if _priority(a) <= _priority(b) else (b, a)
    by_source: dict[str, list[Record]] = {}
    for r in candidates:
        if r.kind == "closure" and r.source in CROSS_SOURCE_CLOSURES:
            by_source.setdefault(r.source, []).append(r)
    sources = sorted(by_source, key=lambda s: _priority(by_source[s][0]))
    for i, s1 in enumerate(sources):
        for s2 in sources[i + 1:]:
            for a in by_source[s1]:
                for b in by_source[s2]:
                    yield a, b


def cross_source(records: list[Record]) -> tuple[list[Record], int]:
    """Returns (records to keep, number merged away). Input order doesn't affect the result."""
    candidates = sorted((r for r in records if r.kind in CROSS_SOURCE_KINDS and r.geometry is not None),
                        key=_priority)
    by_id = {r.id: r for r in candidates}
    parent = {rid: rid for rid in by_id}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in _pairs(candidates):
        if is_same(a, b):
            ra, rb = find(a.id), find(b.id)
            if ra != rb:
                winner, loser = sorted((ra, rb), key=lambda x: _priority(by_id[x]))
                parent[loser] = winner

    kept, merged = [], 0
    for r in records:
        root = find(r.id) if r.id in parent else r.id
        if root != r.id:
            merged += 1
            continue
        kept.append(r)
    for r in candidates:
        root = find(r.id)
        if root != r.id:
            by_id[root].also_reported_by.append({"id": r.id, "source": r.source, "source_id": r.source_id})
    for r in kept:
        r.also_reported_by.sort(key=lambda x: x["id"])
    return kept, merged
