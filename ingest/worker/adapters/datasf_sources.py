"""Normalizers for the DataSF snapshots. Keys, geometry columns and time columns come
from the existing registry in datasf/datasets.py; zone rules from worker.timeutil."""
from __future__ import annotations

from typing import Any

from datasf import DATASETS
from pull.check import FREEWAY_SENTINEL, cnn_key

from ..context import Context
from ..geo import normalize_geometry
from ..records import Record, RecordError, clean_source_fields, natural_key
from ..timeutil import datasf_ts, local_day
from .common import incident_category, truthy

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
    s, e = datasf_ts(start, row.get(start)), datasf_ts(end, row.get(end))
    return {"valid_from": s, "valid_to": e}


# --- static road network and rules ----------------------------------------

ONEWAY = {"B": "both", "F": "from_to", "T": "to_from"}


def streets(row: dict, ctx: Context) -> Record:
    name = row.get("streetname") or " ".join(x for x in (row.get("street"), row.get("st_type")) if x) or None
    return _base("streets", "road_segment", row, attributes={
        "name": name,
        "oneway": ONEWAY.get(row.get("oneway")),
        "from_node_cnn": cnn_key(row.get("f_node_cnn")),
        "to_node_cnn": cnn_key(row.get("t_node_cnn")),
        "from_street": row.get("f_st"),
        "to_street": row.get("t_st"),
        "classcode": row.get("classcode"),
        "network": "datasf_cnn",
    })


def speed_limits(row: dict, ctx: Context) -> Record:
    """Source meaning only; ingestion doesn't invent an effective speed.
    0 = unposted (no sign), 99 = state freeway/ramp that SFMTA doesn't set (pull/check.py)."""
    raw = row.get("speedlimit")
    try:
        mph = int(float(raw)) if raw not in (None, "") else None
    except (TypeError, ValueError):
        raise RecordError(f"speedlimit not numeric: {raw!r}")
    if mph is None:
        raise RecordError("speedlimit missing")
    if mph == FREEWAY_SENTINEL:
        status, posted = "state_managed", None
    elif mph == 0:
        status, posted = "unposted", None
    elif 0 < mph <= 70:
        status, posted = "posted", mph
    else:
        raise RecordError(f"implausible speed limit {mph}")
    return _base("speed_limits", "road_rule", row, attributes={
        "rule_type": "speed_limit", "status": status, "posted_mph": posted, "raw_value": raw})


def _rule(key: str, rule_type: str):
    def normalize(row: dict, ctx: Context) -> Record:
        return _base(key, "road_rule", row, attributes={"rule_type": rule_type})
    return normalize


# --- planned closures / permits -------------------------------------------

def street_closures(row: dict, ctx: Context) -> Record:
    ctype = row.get("type")
    return _base("street_closures", "closure", row, **_span(row, "start_utc", "end_utc"), attributes={
        "closure_type": "street_closure",
        "category": ctype,
        "is_special_event": ctype == "Special Event",
        "name": row.get("case_name"),
        "street": row.get("street"),
        "from_street": row.get("from_st"),
        "to_street": row.get("to_st"),
        "status": row.get("status"),
    })


def street_use_permits(row: dict, ctx: Context) -> Record:
    return _base("street_use_permits", "closure", row, **_span(row, "permit_start_date", "permit_end_date"), attributes={
        "closure_type": "street_use_permit",
        "permit_number": row.get("permit_number"),
        "permit_type": row.get("permit_type"),
        "status": row.get("status"),
        "street": row.get("streetname"),
    })


def excavation_permits(row: dict, ctx: Context) -> Record:
    # cnn-only (no geometry): enrichment derives geometry from the street network.
    return _base("excavation_permits", "closure", row, **_span(row, "effective_date", "expiration_date"), attributes={
        "closure_type": "excavation",
        "permit_number": row.get("permit_number"),
        "status": row.get("status"),
    })


def parking_signs(row: dict, ctx: Context) -> Record:
    try:
        start, end = local_day(row.get("startdate")), local_day(row.get("enddate"), end=True)
    except ValueError as e:
        raise RecordError(f"sign dates: {e}")
    return _base("parking_signs", "closure", row, valid_from=start, valid_to=end,
                 observed_at=datasf_ts("datetimeentered", row.get("datetimeentered")), attributes={
                     "closure_type": "temporary_no_parking",
                     "side_of_street": row.get("sideofstreet"),
                 })


# --- live -------------------------------------------------------------------

def police_dispatch(row: dict, ctx: Context) -> Record:
    rec = _base("police_dispatch", "incident", row,
                observed_at=datasf_ts("received_datetime", row.get("received_datetime")),
                valid_to=datasf_ts("close_datetime", row.get("close_datetime")))
    call_type = row.get("call_type_final_desc") or row.get("call_type_original_desc")
    rec.valid_from = rec.observed_at
    rec.attributes = {
        "incident_source_type": "police_dispatch",
        "call_type": call_type,
        "category": incident_category(call_type),
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


NORMALIZERS = {
    "streets": streets,
    "speed_limits": speed_limits,
    "clearance_heights": _rule("clearance_heights", "clearance_height"),
    "parking_regulations": _rule("parking_regulations", "parking_regulation"),
    "tow_away_zones": _rule("tow_away_zones", "tow_away_zone"),
    "street_sweeping": _rule("street_sweeping", "street_sweeping"),
    "street_closures": street_closures,
    "street_use_permits": street_use_permits,
    "excavation_permits": excavation_permits,
    "parking_signs": parking_signs,
    "police_dispatch": police_dispatch,
}
