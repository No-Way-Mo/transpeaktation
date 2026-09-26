"""Snapshot row -> Record, one normalizer per source (ported from ingestion-workers-v1).

Changes from v1, each found on real data (see the v1/tuff comparison):
  * Caltrans: key is the row's `index` (closureID-logNumber-start date-time), unique per closure
    window. One closureID repeats once per scheduled day, so keying on closureID alone kept 163
    of 1,542 rows and dropped every later window; closureID + logNumber still repeats weekly.
  * Police dispatch: only traffic calls (collision, hazard, closure) are kept. v1 stored every
    call, and 97% were citations, "passing call", "suspicious person" and similar.
  * `is_closure` on every record: True only when the road is closed to traffic, so routing can
    tell a full closure from a lane closure or a permit.
  * Parking signs are no longer road incidents (temporary no-parking signs close curb, not road).
"""
from __future__ import annotations

from typing import Any

from datasf import DATASETS
from pull.check import chp_point, cnn_key

from .common import incident_category, truthy
from .geom import BAY_BBOX, GeometryError, inside, normalize_geometry, point
from .records import Record, RecordError, clean_source_fields, natural_key
from .timeutil import chp_ts, datasf_ts, epoch, iso

BAY_DISPATCH = "GGCC"  # CHP Golden Gate communications center
TRAFFIC_CATEGORIES = {"collision", "hazard", "closure"}
CALTRANS_FULL = {"Full"}


def _base(key: str, kind: str, row: dict, **kw: Any) -> Record:
    ds = DATASETS[key]
    geom = normalize_geometry(row.get(ds.geo_field)) if ds.geo_field else None
    cnn = cnn_key(row.get("cnn"))
    return Record(
        kind=kind,
        source=key,
        source_id=natural_key(row, ds.id_field),
        geometry=geom,
        road_ref={"cnn": cnn, "match": "unknown"} if cnn else None,
        source_fields=clean_source_fields(row, drop=[ds.geo_field] if ds.geo_field else []),
        **kw,
    )


def _span(row: dict, start: str, end: str) -> dict:
    return {"valid_from": datasf_ts(start, row.get(start)), "valid_to": datasf_ts(end, row.get(end))}


# --- DataSF planned closures / permits ----------------------------------------

def street_closures(row: dict) -> Record:
    ctype = row.get("type")
    return _base("street_closures", "closure", row, **_span(row, "start_utc", "end_utc"), attributes={
        "closure_type": "street_closure",
        "category": ctype,
        "is_closure": True,  # Temporary Street Closures: special events, traffic permits, Shared Spaces
        "is_special_event": ctype == "Special Event",
        "name": row.get("case_name"),
        "street": row.get("street"),
        "from_street": row.get("from_st"),
        "to_street": row.get("to_st"),
        "status": row.get("status"),
    })


def street_use_permits(row: dict) -> Record:
    return _base("street_use_permits", "closure", row, **_span(row, "permit_start_date", "permit_end_date"), attributes={
        "closure_type": "street_use_permit",
        "is_closure": False,  # narrows a lane or curb; the road stays open
        "permit_number": row.get("permit_number"),
        "permit_type": row.get("permit_type"),
        "status": row.get("status"),
        "street": row.get("streetname"),
    })


def excavation_permits(row: dict) -> Record:
    # cnn-only (no geometry): enrichment derives geometry from the street network.
    return _base("excavation_permits", "closure", row, **_span(row, "effective_date", "expiration_date"), attributes={
        "closure_type": "excavation",
        "is_closure": False,
        "permit_number": row.get("permit_number"),
        "status": row.get("status"),
    })


# --- DataSF police dispatch -----------------------------------------------------

def police_dispatch(row: dict) -> Record | None:
    call_type = row.get("call_type_final_desc") or row.get("call_type_original_desc")
    category = incident_category(call_type)
    if category not in TRAFFIC_CATEGORIES:
        return None  # not a traffic call: never stored
    rec = _base("police_dispatch", "incident", row,
                observed_at=datasf_ts("received_datetime", row.get("received_datetime")),
                valid_to=datasf_ts("close_datetime", row.get("close_datetime")))
    rec.valid_from = rec.observed_at
    rec.attributes = {
        "incident_source_type": "police_dispatch",
        "call_type": call_type,
        "category": category,
        "is_closure": category == "closure",
        "priority": row.get("priority_final") or row.get("priority_original"),
        "disposition": row.get("disposition"),
        "location_text": row.get("intersection_name"),
        "sensitive": truthy(row.get("sensitive_call")),
    }
    if rec.geometry is None:
        if rec.attributes["sensitive"]:
            rec.location_status = "withheld"  # withheld by design: never geocode
        else:
            rec.location_status = "unlocated"
            if row.get("intersection_name"):
                rec.geocode_query = f"{row['intersection_name']}, San Francisco, CA"
    return rec


# --- Caltrans D4 lane closures ------------------------------------------------

def _caltrans_point(loc: dict, end: str) -> dict | None:
    lon, lat = loc.get(f"{end}Longitude"), loc.get(f"{end}Latitude")
    if lon in (None, "") or lat in (None, ""):
        return None
    try:
        return point(lon, lat)
    except GeometryError:
        return None


def caltrans_lane_closures(row: dict) -> Record | None:
    closure = row.get("closure") or {}
    location = row.get("location") or {}
    begin, end = location.get("begin") or {}, location.get("end") or {}
    cid = closure.get("closureID")
    source_id = row.get("index") or cid  # index is unique per closure window; closureID is not
    if source_id in (None, ""):
        raise RecordError("no index / closureID")
    b, e = _caltrans_point(begin, "begin"), _caltrans_point(end, "end")
    if b is None:
        raise RecordError("no valid begin coordinates")
    geom = {"type": "LineString", "coordinates": [b["coordinates"], e["coordinates"]]} \
        if e and e["coordinates"] != b["coordinates"] else b
    if not inside(geom, BAY_BBOX):
        return None  # filtered: outside the Bay Area
    ts = closure.get("closureTimestamp") or {}
    indefinite = truthy(ts.get("isClosureEndIndefinite"))
    lanes = str(closure.get("lanesClosed") or "")
    return Record(
        kind="closure", source="caltrans_lane_closures", source_id=str(source_id), geometry=geom,
        valid_from=epoch(ts.get("closureStartEpoch")),
        valid_to=None if indefinite else epoch(ts.get("closureEndEpoch")),
        attributes={
            "closure_type": "lane_closure",
            "is_closure": closure.get("typeOfClosure") in CALTRANS_FULL or lanes.split(",")[0].strip() == "All",
            "closure_id": cid,
            "route": begin.get("beginRoute"),
            "direction": location.get("travelFlowDirection"),
            "county": begin.get("beginCounty"),
            "location_text": begin.get("beginLocationName") or begin.get("beginFreeFormDescription"),
            "end_location_text": end.get("endLocationName"),
            "lanes_closed": closure.get("lanesClosed"),
            "total_lanes": closure.get("totalExistingLanes"),
            "type_of_closure": closure.get("typeOfClosure"),
            "type_of_work": closure.get("typeOfWork"),
            "facility": closure.get("facility"),
            "end_indefinite": indefinite,
        },
        source_fields=clean_source_fields(row),
    )


# --- CHP incidents ------------------------------------------------------------

def chp_incidents(row: dict) -> Record | None:
    if not row.get("log_id"):
        raise RecordError("missing log_id")
    observed = chp_ts(row.get("LogTime"))
    if observed is None:
        raise RecordError("missing LogTime")
    pts = chp_point(row)  # [] for "0:0" / unparseable
    geom = point(*pts[0]) if pts else None
    in_bay = row.get("center") == BAY_DISPATCH or row.get("dispatch") == BAY_DISPATCH
    if geom is not None and not inside(geom, BAY_BBOX):
        return None  # statewide feed: keep the Bay Area only
    if geom is None and not in_bay:
        return None
    details = []
    for d in row.get("details") or []:
        try:
            t = iso(chp_ts(d.get("time")))
        except ValueError:
            t = None
        details.append({"time": t, "text": d.get("text")})
    category = incident_category(row.get("LogType"))
    rec = Record(
        kind="incident", source="chp_incidents", source_id=str(row["log_id"]), geometry=geom,
        observed_at=observed, valid_from=observed,
        location_status="exact" if geom else "unlocated",
        attributes={
            "incident_source_type": "chp",
            "call_type": row.get("LogType"),
            "category": category,
            "is_closure": category == "closure",
            "location_text": row.get("Location"),
            "area": row.get("Area"),
            "center": row.get("center"),
            "dispatch": row.get("dispatch"),
            "details": details,
        },
        source_fields=clean_source_fields(row, drop=["details"]),
    )
    if geom is None and row.get("Location"):
        rec.geocode_query = f"{row['Location']}, {row.get('Area') or 'Bay Area'}, CA"
    return rec


NORMALIZERS = {
    "street_closures": street_closures,
    "street_use_permits": street_use_permits,
    "excavation_permits": excavation_permits,
    "police_dispatch": police_dispatch,
    "caltrans_lane_closures": caltrans_lane_closures,
    "chp_incidents": chp_incidents,
}
