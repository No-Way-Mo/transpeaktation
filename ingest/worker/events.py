"""Events: `python -m pull predicthq_events` snapshot -> Mongo `events` + `venues` (DESIGN.md §4).

One doc per PredictHQ event, `_id = event_id` (`evt_<sha1[:16]>`). The source's own view sits under
`sources.predicthq` and `source_names` is added to, so a later 511 / DataSF merge adds blocks instead of replacing
this one. Venues: a PredictHQ venue near a seeded one (worker/seeds/venues.json) becomes that seed, which carries
the capacity PredictHQ doesn't publish; any other venue is `phq:<entity_id>`.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from datasf.datasets import SF_TZ
from pull.feeds import SF_BBOX

from .geo import haversine_m
from .incidents.job import load_snapshot
from .incidents.records import dumps

SOURCE = "predicthq_events"
SEEDS = Path(__file__).with_name("seeds") / "venues.json"
SCHEMA_VERSION = 1

# PredictHQ category -> DESIGN.md §4 vocabulary (api/app/model.py TYPE_FACTOR keys).
CATEGORY = {"concerts": "concert", "sports": "sports", "festivals": "festival", "performing-arts": "performing_arts",
            "conferences": "conference", "expos": "conference", "community": "community",
            "public-holidays": "holiday"}
# deleted_reason -> status. api/ only plans around status "active".
DELETED_STATUS = {"cancelled": "cancelled", "postponed": "postponed"}  # duplicate / invalid / other -> archived
SEED_NAME_M = 800   # same name (or alias) within this -> the seeded venue
SEED_NEAR_M = 60    # any name this close -> the seeded venue (Opera House and Davies are ~80 m apart)
ALL_DAY = timedelta(hours=23)


class Sink(Protocol):
    def write_events(self, items: list[tuple[dict, dict, dict]]) -> None: ...
    def write_venues(self, items: list[tuple[dict, dict, dict]]) -> None: ...
    def archive_missing_events(self, source: str, keep_ids: list[str], start: datetime, end: datetime) -> int: ...


def event_id(source: str, source_id: str) -> str:
    return "evt_" + hashlib.sha1(f"{source}:{source_id}".encode()).hexdigest()[:16]


def _norm(name: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", re.sub(r"^the\s+", "", str(name or "").lower())).strip()


def _ts(value: Any, *, local: bool) -> datetime | None:
    """PredictHQ times are UTC, except events with no `timezone` (holidays): those are SF wall-clock."""
    if not value:
        return None
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if local:
        return dt.replace(tzinfo=SF_TZ).astimezone(timezone.utc)
    if dt.tzinfo is None:
        raise ValueError(f"naive time {value!r} on an event with a timezone")
    return dt.astimezone(timezone.utc)


def _inside_sf(lon: float, lat: float) -> bool:
    return SF_BBOX[0] <= lon <= SF_BBOX[2] and SF_BBOX[1] <= lat <= SF_BBOX[3]


# --- venues ---------------------------------------------------------------------------------------------------

def load_seeds(path: Path = SEEDS) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["venues"]


def match_seed(name: str, lon: float, lat: float, seeds: list[dict]) -> dict | None:
    """The seed with the same name (or alias) nearby; failing that, any seed right next to the point."""
    n = _norm(name)
    by_name, by_place = [], []
    for s in seeds:
        d = haversine_m((lon, lat), (s["lon"], s["lat"]))
        names = [_norm(x) for x in [s["name"], *s.get("aliases", [])]]
        if n and d <= SEED_NAME_M and any(x and (x in n or n in x) for x in names):
            by_name.append((d, s["slug"], s))
        elif d <= SEED_NEAR_M:
            by_place.append((d, s["slug"], s))
    best = min(by_name or by_place, default=None)
    return best[2] if best else None


def seed_venue_doc(s: dict) -> tuple[dict, dict, dict]:
    return ({"_id": f"seed:{s['slug']}"},
            {"name": s["name"], "aliases": s.get("aliases", []), "keys": s.get("keys", []),
             "location": {"type": "Point", "coordinates": [s["lon"], s["lat"]]},
             "capacity": s["capacity"], "capacity_note": "approximate, verify", "source": "seed"},
            {})


# --- events ---------------------------------------------------------------------------------------------------

def normalize(row: dict, seeds: list[dict]) -> tuple[dict, dict | None] | str:
    """One PredictHQ event -> ({_id, set, add}, venue (entity_id, name, lon, lat, seed) or None), or a skip reason."""
    loc = row.get("location") or []
    if len(loc) != 2:
        return "no_location"
    lon, lat = float(loc[0]), float(loc[1])
    if not _inside_sf(lon, lat):
        return "outside_sf"
    local = not row.get("timezone")
    start = _ts(row.get("start"), local=local)
    if start is None:
        return "no_start"
    end, predicted_end = _ts(row.get("end"), local=local), _ts(row.get("predicted_end"), local=local)
    end_is_predicted = False
    if (end is None or end <= start) and predicted_end and predicted_end > start:
        end, end_is_predicted = predicted_end, True
    elif end is not None and end <= start:
        end = None  # no known end: api/ uses a default length per category
    all_day = local or bool(end and end - start >= ALL_DAY)

    labels = set(row.get("labels") or []) | {l.get("label") for l in row.get("phq_labels") or [] if isinstance(l, dict)}
    category = CATEGORY.get(row.get("category"), "other")
    if "parade" in labels:
        category = "parade"
    state = row.get("state") or "active"
    status = "active" if state in ("active", "predicted") else DELETED_STATUS.get(row.get("deleted_reason"), "archived")

    ent = next((e for e in row.get("entities") or [] if e.get("type") == "venue"), None)
    venue = seed = None
    if ent:
        seed = match_seed(ent.get("name"), lon, lat, seeds)
        venue = {"entity_id": ent["entity_id"], "name": ent.get("name"), "address": ent.get("formatted_address"),
                 "lon": lon, "lat": lat, "seed": seed}
    venue_id = f"seed:{seed['slug']}" if seed else (f"phq:{ent['entity_id']}" if ent else None)

    geometry = (row.get("geo") or {}).get("geometry")
    view = {"id": row["id"], "state": state, "deleted_reason": row.get("deleted_reason"),
            "category": row.get("category"), "labels": sorted(l for l in labels if l), "scope": row.get("scope"),
            "phq_attendance": row.get("phq_attendance"), "rank": row.get("rank"), "local_rank": row.get("local_rank"),
            "start": row.get("start"), "end": row.get("end"), "predicted_end": row.get("predicted_end"),
            "timezone": row.get("timezone"), "updated": row.get("updated")}
    doc = {
        "title": row.get("title"), "category": category,
        "start_time": start, "end_time": end, "end_is_predicted": end_is_predicted, "all_day": all_day,
        "location": {"type": "Point", "coordinates": [lon, lat]},
        "area": geometry if geometry and geometry.get("type") not in (None, "Point") else None,
        "venue_id": venue_id, "venue_name": (seed or {}).get("name") or (ent or {}).get("name"),
        "capacity": (seed or {}).get("capacity"), "attendance": row.get("phq_attendance"),
        "rank": row.get("rank"), "local_rank": row.get("local_rank"), "status": status,
        "archived_reason": None if status == "active" else f"predicthq_{row.get('deleted_reason') or state}",
        "schema_version": SCHEMA_VERSION,
    }
    content_hash = hashlib.sha1(dumps({**doc, "_view": view}, sort_keys=True).encode()).hexdigest()[:16]
    doc["sources.predicthq"] = {"id": row["id"], "updated": _ts(row.get("updated"), local=False),
                                "hash": content_hash, "data": view}
    return {"_id": event_id("predicthq", row["id"]), "set": doc, "add": {"source_names": "predicthq"}}, venue


def phq_venue_doc(v: dict) -> tuple[dict, dict, dict]:
    return ({"_id": f"phq:{v['entity_id']}"},
            {"name": v["name"], "address": v.get("address"),
             "location": {"type": "Point", "coordinates": [v["lon"], v["lat"]]}, "source": "predicthq"},
            {"phq_entity_ids": v["entity_id"]})


# --- job ------------------------------------------------------------------------------------------------------

def complete_window(snap: dict) -> tuple[datetime, datetime] | None:
    """[pulled_at, start of the last day asked for] when the pull got every page, else None. A future event in that
    window that this pull didn't return has dropped out of PredictHQ (or below the rank cut) without a "deleted"."""
    meta = snap.get("meta") or {}
    if meta.get("truncated") is not False or not meta.get("active.lte") or not snap.get("pulled_at"):
        return None
    last_day = datetime.fromisoformat(meta["active.lte"]).replace(tzinfo=SF_TZ).astimezone(timezone.utc)
    return datetime.fromisoformat(snap["pulled_at"]), last_day


class EventJob:
    def __init__(self, raw_dir: Path, sink: Sink, *, seeds: list[dict] | None = None, out_dir: Path | None = None):
        self.raw_dir, self.sink = raw_dir, sink
        self.seeds = load_seeds() if seeds is None else seeds
        self.out_dir = out_dir or raw_dir.parent

    def run(self) -> dict:
        try:
            snap = load_snapshot(self.raw_dir, SOURCE)
        except (OSError, ValueError) as e:
            return {"status": "failed", "error": str(e)}
        # Seeds are written every run, matched or not, so api/ always has their capacities.
        venues: dict[str, tuple[dict, dict, dict]] = {f"seed:{s['slug']}": seed_venue_doc(s) for s in self.seeds}
        if snap is None:
            self.sink.write_venues(list(venues.values()))
            return {"status": "missing", "note": f"not pulled yet (python -m pull {SOURCE}; needs PREDICTHQ_TOKEN)",
                    "venues": len(venues)}
        st: Counter = Counter()
        events: list[tuple[dict, dict, dict]] = []
        quarantine: list[dict] = []
        for i, row in enumerate(snap["records"]):
            st["raw"] += 1
            try:
                out = normalize(row, self.seeds)
            except Exception as e:  # malformed row: quarantine it, keep the batch going
                quarantine.append({"source": SOURCE, "index": i, "errors": [f"{type(e).__name__}: {e}"], "raw": row})
                continue
            if isinstance(out, str):
                st[out] += 1
                continue
            ev, v = out
            events.append(({"_id": ev["_id"]}, ev["set"], ev["add"]))
            st[ev["set"]["status"]] += 1
            if v and v["seed"]:
                _, _, add = venues[f"seed:{v['seed']['slug']}"]
                add.setdefault("phq_entity_ids", []).append(v["entity_id"])
                st["at_seeded_venue"] += 1
            elif v:
                venues.setdefault(f"phq:{v['entity_id']}", phq_venue_doc(v))
        if events:
            self.sink.write_events(events)
        self.sink.write_venues(list(venues.values()))
        self._write_quarantine(quarantine)
        report = {"status": "ok", "pulled_at": snap.get("pulled_at"), "meta": snap.get("meta"), **dict(st),
                  "events": len(events), "venues": len(venues), "rejected": len(quarantine)}
        if (window := complete_window(snap)) and events:
            report["archived_missing"] = self.sink.archive_missing_events(
                "predicthq", [f["_id"] for f, _, _ in events], *window)
        return report

    def _write_quarantine(self, rows: list[dict]) -> None:
        path = self.out_dir / "quarantine" / f"{SOURCE}.jsonl"
        if rows:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("".join(dumps(q) + "\n" for q in rows), encoding="utf-8")
        elif path.exists():
            path.unlink()
