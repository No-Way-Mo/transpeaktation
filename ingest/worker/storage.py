"""Record -> store mapping, following the team contract (AGENTS.md "Data stores" and
contracts/tiger_schema.sql). Contract field names are join keys: keep them.

MongoDB `transpeaktation` (upserts):
    road_segments   OSM drive-graph edges; key `segment_id` = "u-v-key"; `cnn` = matched DataSF
                    street; DataSF speed limit for that cnn embedded as `speed_limit`.
    road_incidents  closures, permits, no-parking signs, lane closures, dispatch, CHP;
                    key `source`+`source_id`; `location`, `start_time`, `end_time`, `road_segment_ids`.
Tiger Data `tsdb` (append-only history):
    traffic_metrics Mapbox corridor speeds per OSM edge.

No contract destination (normalized + dumped only, reported as `unrouted`):
    DataSF `streets` (used as the cnn index), speed limits (embedded instead), clearance
    heights, parking regulations, tow-away zones, street sweeping, OSM turn restrictions.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .records import SCHEMA_VERSION, Record

MONGO = "mongo"
TIGER = "tiger"

ROAD_SEGMENTS = "road_segments"
ROAD_INCIDENTS = "road_incidents"

# Contract indexes (AGENTS.md). Created only with --ensure-indexes; create_index is a no-op if present.
MONGO_INDEXES: dict[str, list[tuple[list[tuple[str, Any]], dict[str, Any]]]] = {
    ROAD_SEGMENTS: [([("segment_id", 1)], {"unique": True}), ([("cnn", 1)], {}),
                    ([("geometry", "2dsphere")], {})],
    ROAD_INCIDENTS: [([("source", 1), ("source_id", 1)], {"unique": True}), ([("location", "2dsphere")], {}),
                     ([("start_time", 1), ("end_time", 1)], {}), ([("road_segment_ids", 1)], {})],
}


@dataclass(frozen=True)
class TigerTable:
    name: str
    columns: tuple[str, ...]
    # Reruns skip rows whose (source, time) already exist: the table has no unique key,
    # and one poll's rows are always inserted in a single transaction.
    idempotency: tuple[str, str] = ("source", "time")


TRAFFIC_METRICS = TigerTable("traffic_metrics", ("time", "road_segment_id", "source", "speed_mph",
                                                 "free_flow_speed_mph", "travel_time_sec", "congestion_ratio"))
TIGER_TABLES: dict[str, TigerTable] = {TRAFFIC_METRICS.name: TRAFFIC_METRICS}


def destination(r: Record) -> tuple[str, str] | None:
    """(store, collection_or_table), or None when the contract has no home for the record."""
    if r.kind == "road_segment" and r.source == "osm_drive_graph":
        return MONGO, ROAD_SEGMENTS
    if r.kind in ("closure", "incident"):
        return MONGO, ROAD_INCIDENTS
    if r.kind == "traffic_metric":
        return TIGER, TRAFFIC_METRICS.name
    return None


def _common(r: Record, now: datetime) -> dict[str, Any]:
    return {"source": r.source, "location_status": r.location_status, "provenance": r.provenance(),
            "schema_version": SCHEMA_VERSION, "last_ingested_at": now}


def road_segment_doc(r: Record, now: datetime) -> tuple[dict, dict]:
    a = r.attributes
    ref = r.road_ref or {}
    doc = {
        "segment_id": r.source_id,
        **{k: a.get(k) for k in ("u", "v", "key", "osmid", "name", "highway", "oneway", "reversed", "lanes",
                                 "maxspeed_raw", "maxspeed_mph", "access", "length_m")},
        "geometry": r.geometry,
        **_common(r, now),
    }
    if "cnn" in r.computed:
        doc.update(cnn=ref.get("cnn"), cnn_match_distance_m=ref.get("distance_m"))
    if "speed_limit" in r.computed:
        doc["speed_limit"] = a.get("speed_limit")
    return {"segment_id": r.source_id}, doc


def road_incident_doc(r: Record, now: datetime) -> tuple[dict, dict]:
    a = r.attributes
    ref = r.road_ref or {}
    doc = {
        "source_id": r.source_id,
        "incident_type": r.kind,  # closure | incident
        "category": a.get("closure_type") or a.get("category"),
        "location": r.geometry,
        "start_time": r.valid_from,
        "end_time": r.valid_to,
        "reported_at": r.observed_at,
        "cnn": ref.get("cnn"),
        "cnn_match": ref.get("match"),
        "details": a,
        "source_fields": r.source_fields,
        **_common(r, now),
    }
    if "road_segment_ids" in r.computed:
        doc["road_segment_ids"] = r.road_segment_ids
    return {"source": r.source, "source_id": r.source_id}, doc


def mongo_doc(r: Record, now: datetime) -> tuple[dict, dict]:
    """(upsert filter, document) for a Mongo-bound record."""
    return road_segment_doc(r, now) if r.kind == "road_segment" else road_incident_doc(r, now)


def tiger_row(r: Record) -> dict[str, Any]:
    a = r.attributes
    return {"time": r.observed_at, "road_segment_id": a["road_segment_id"], "source": a["tiger_source"],
            "speed_mph": a.get("speed_mph"), "free_flow_speed_mph": a.get("free_flow_speed_mph"),
            "travel_time_sec": a.get("travel_time_sec"), "congestion_ratio": a.get("congestion_ratio")}


def debug_doc(r: Record, now: datetime) -> dict[str, Any]:
    """Local dump shape: the store document when there is one, else the full record."""
    dest = destination(r)
    if dest and dest[0] == MONGO:
        f, d = mongo_doc(r, now)
        return {**f, **d, "_store": f"{MONGO}.{dest[1]}"}
    if dest:
        return {**tiger_row(r), "_store": f"{TIGER}.{dest[1]}", "_debug": r.attributes}
    return {"_store": None, "kind": r.kind, "source": r.source, "source_id": r.source_id,
            "geometry": r.geometry, "road_ref": r.road_ref, "valid_from": r.valid_from, "valid_to": r.valid_to,
            "observed_at": r.observed_at, "attributes": r.attributes, "provenance": r.provenance()}
