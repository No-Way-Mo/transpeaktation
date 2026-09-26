"""Normalizers for the non-DataSF snapshots: Caltrans, CHP, OSM, 511."""
from __future__ import annotations

import re
from typing import Any

from pull.check import chp_point

from ..context import Context
from ..geo import BAY_BBOX, GeometryError, inside, point
from ..records import Record, RecordError, clean_source_fields
from ..timeutil import chp_ts, epoch, iso
from .common import incident_category, truthy

BAY_DISPATCH = "GGCC"  # CHP Golden Gate communications center (see pull/check.py)


# --- Caltrans D4 lane closures ----------------------------------------------

def _caltrans_point(loc: dict, end: str) -> dict | None:
    lon, lat = loc.get(f"{end}Longitude"), loc.get(f"{end}Latitude")
    if lon in (None, "") or lat in (None, ""):
        return None
    try:
        return point(lon, lat)
    except GeometryError:
        return None


def caltrans_lane_closures(row: dict, ctx: Context) -> Record | None:
    closure = row.get("closure") or {}
    location = row.get("location") or {}
    begin, end = location.get("begin") or {}, location.get("end") or {}
    source_id = closure.get("closureID") or closure.get("logNumber") or row.get("index")
    if source_id in (None, ""):
        raise RecordError("no closureID / logNumber / index")
    b, e = _caltrans_point(begin, "begin"), _caltrans_point(end, "end")
    if b is None:
        raise RecordError("no valid begin coordinates")
    if e and e["coordinates"] != b["coordinates"]:
        geom = {"type": "LineString", "coordinates": [b["coordinates"], e["coordinates"]]}
    else:
        geom = b
    if not inside(geom, BAY_BBOX):
        return None  # filtered: outside the Bay Area
    ts = closure.get("closureTimestamp") or {}
    indefinite = truthy(ts.get("isClosureEndIndefinite"))
    return Record(
        kind="closure", source="caltrans_lane_closures", source_id=str(source_id), geometry=geom,
        valid_from=epoch(ts.get("closureStartEpoch")),
        valid_to=None if indefinite else epoch(ts.get("closureEndEpoch")),
        attributes={
            "closure_type": "lane_closure",
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


# --- CHP incidents ----------------------------------------------------------

def chp_incidents(row: dict, ctx: Context) -> Record | None:
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
    rec = Record(
        kind="incident", source="chp_incidents", source_id=str(row["log_id"]), geometry=geom,
        observed_at=observed, valid_from=observed,
        location_status="exact" if geom else "unlocated",
        attributes={
            "incident_source_type": "chp",
            "call_type": row.get("LogType"),
            "category": incident_category(row.get("LogType")),
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


# --- OpenStreetMap ------------------------------------------------------------

def _maxspeed_mph(v: Any) -> float | None:
    """'25 mph' / '40' (km/h per OSM default) / ['25 mph', '30 mph'] -> lowest mph."""
    vals = v if isinstance(v, list) else [v]
    out = []
    for x in vals:
        m = re.match(r"\s*(\d+(?:\.\d+)?)\s*(mph)?", str(x or ""))
        if m:
            n = float(m.group(1))
            out.append(n if m.group(2) else round(n / 1.609344, 1))
    return min(out) if out else None


def osm_drive_graph(row: dict, ctx: Context) -> Record:
    try:
        u, v, k = str(int(row["u"])), str(int(row["v"])), str(int(row.get("key") or 0))
    except (KeyError, TypeError, ValueError):
        raise RecordError("edge needs integer u, v")
    geom = ctx.osm.geometry.get(f"{u}-{v}-{k}") if ctx.osm else None
    oneway = row.get("oneway")
    return Record(
        kind="road_segment", source="osm_drive_graph", source_id=f"{u}-{v}-{k}", geometry=geom,
        location_status="exact" if geom else "network_ref",
        attributes={
            "network": "osm",
            "u": u, "v": v, "key": k,
            "osmid": row.get("osmid"),
            "name": row.get("name"),
            "highway": row.get("highway"),
            "oneway": truthy(oneway) if oneway is not None else None,
            "reversed": row.get("reversed"),
            "lanes": row.get("lanes"),
            "maxspeed_raw": row.get("maxspeed"),
            "maxspeed_mph": _maxspeed_mph(row.get("maxspeed")),
            "access": row.get("access"),
            "length_m": float(row["length"]) if row.get("length") not in (None, "") else None,
        },
    )


def osm_turn_restrictions(row: dict, ctx: Context) -> Record:
    if row.get("type") != "relation" or row.get("id") is None:
        raise RecordError("not an OSM relation with an id")
    tags = row.get("tags") or {}
    members = [{"role": m.get("role"), "type": m.get("type"), "ref": m.get("ref")} for m in row.get("members") or []]
    if not {"from", "to"} <= {m["role"] for m in members}:
        raise RecordError("restriction lacks from/to members")
    return Record(
        kind="road_rule", source="osm_turn_restrictions", source_id=str(row["id"]),
        location_status="network_ref",
        attributes={
            "rule_type": "turn_restriction",
            "restriction": tags.get("restriction") or next((v for k, v in tags.items() if k.startswith("restriction:")), None),
            "except": tags.get("except"),
            "members": members,
            "tags": tags,
        },
    )


# --- 511.org (unverified) -----------------------------------------------------

AWAITING_511 = ("511 response shape unverified: adapter awaits a real fixture (needs SF511_API_KEY); "
                "records left in the raw snapshot, nothing written")

NORMALIZERS = {
    "caltrans_lane_closures": caltrans_lane_closures,
    "chp_incidents": chp_incidents,
    "osm_drive_graph": osm_drive_graph,
    "osm_turn_restrictions": osm_turn_restrictions,
}
UNSUPPORTED = {
    "sf511_traffic_events": AWAITING_511,
    "sf511_muni_vehicles": AWAITING_511,
}
