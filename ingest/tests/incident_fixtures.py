"""Raw snapshot rows in the exact shape `python -m pull` writes (from ingestion-workers-v1's fixtures)."""
from __future__ import annotations

import json
from pathlib import Path

from pull.feeds import parse_chp

PULLED_AT = "2026-09-26T00:30:00+00:00"

STREETS = [
    {"cnn": "100", "streetname": "MARKET ST", "oneway": "B", "f_node_cnn": "900", "t_node_cnn": "901",
     "f_st": "4TH ST", "t_st": "5TH ST", "active": True,
     "line": {"type": "LineString", "coordinates": [[-122.42, 37.77], [-122.419, 37.77]]},
     ":@computed_region_abc": "7"},
    {"cnn": "200", "streetname": "5TH ST", "oneway": "F", "f_node_cnn": "901", "t_node_cnn": "902",
     "line": {"type": "MultiLineString", "coordinates": [[[-122.419, 37.77], [-122.419, 37.771]]]}},
]

STREET_CLOSURES = [
    {"objectid": "10", "type": "Special Event", "case_name": "Fleet Week", "street": "MARKET ST",
     "from_st": "4TH ST", "to_st": "5TH ST", "status": "Approved",
     "start_utc": "2026-09-26T10:00:00.000", "end_utc": "2026-09-27T02:00:00.000",
     "shape": {"type": "LineString", "coordinates": [[-122.42, 37.77], [-122.419, 37.77]]}},
    {"objectid": "11", "type": "Construction", "start_utc": "2026-09-27T10:00:00.000",
     "end_utc": "2026-09-26T10:00:00.000", "shape": {"type": "Point", "coordinates": [-122.42, 37.77]}},
]

EXCAVATION = [
    {"permit_number": "EX1", "cnn": "100", "effective_date": "2026-09-20T00:00:00.000",
     "expiration_date": "2026-10-10T00:00:00.000"},
    {"permit_number": "EX1", "cnn": "901", "effective_date": "2026-09-20T00:00:00.000",
     "expiration_date": "2026-10-10T00:00:00.000"},
    {"permit_number": "EX1", "cnn": "100", "effective_date": "2026-09-20T00:00:00.000",
     "expiration_date": "2026-10-10T00:00:00.000"},  # duplicate natural key
]

POLICE = [
    {"id": "p1", "received_datetime": "2026-09-25T17:10:00.000", "call_type_final_desc": "Traffic Collision",
     "intersection_name": "MARKET ST \\ 5TH ST",
     "intersection_point": {"type": "Point", "coordinates": [-122.4191, 37.7751]}},
    {"id": "p2", "received_datetime": "2026-09-25T17:20:00.000", "call_type_final_desc": "Well Being Check",
     "sensitive_call": True},
    {"id": "p3", "received_datetime": "2026-09-25T17:30:00.000", "call_type_final_desc": "Traffic Hazard",
     "sensitive_call": False, "intersection_name": "MISSION ST \\ 6TH ST"},
    {"id": "p4", "received_datetime": "not a time"},
]

CHP_XML = '''<?xml version="1.0" ?>
<State><Center ID = "GGHB"><Dispatch ID = "GGCC">
<Log ID = "260925GG0001"><LogTime>"Sep 25 2026  5:00PM"</LogTime><LogType>"1183-Trfc Collision-Unkn Inj"</LogType>
<Location>"US101 N / Market St"</Location><Area>"San Francisco"</Area><LATLON>"37775000:122419000"</LATLON>
<LogDetails><details><DetailTime>"Sep 25 2026  5:02PM"</DetailTime><IncidentDetail>"2 VEHS"</IncidentDetail></details></LogDetails></Log>
<Log ID = "260925GG0002"><LogTime>"Sep 25 2026  5:30PM"</LogTime><LogType>"1125-Traffic Hazard"</LogType>
<Location>"I280 S / Alemany Blvd"</Location><Area>"San Francisco"</Area><LATLON>"0:0"</LATLON></Log>
</Dispatch></Center><Center ID = "LACC"><Dispatch ID = "LACC">
<Log ID = "260925LA0001"><LogTime>"Sep 25 2026  5:10PM"</LogTime><LogType>"1183-Trfc Collision-Unkn Inj"</LogType>
<Location>"I5"</Location><Area>"Los Angeles"</Area><LATLON>"34050000:118240000"</LATLON></Log>
</Dispatch></Center></State>'''


def caltrans_row(cid="C1", lat="37.7300", lon="-122.4000", end=("37.7310", "-122.4010"), start="1790000000",
                 stop="1790030000", county="San Francisco"):
    return {"index": cid, "closure": {"closureID": cid, "logNumber": "1", "lanesClosed": "1",
                                      "closureTimestamp": {"closureStartEpoch": start, "closureEndEpoch": stop,
                                                           "isClosureEndIndefinite": "false"}},
            "location": {"travelFlowDirection": "North",
                         "begin": {"beginLatitude": lat, "beginLongitude": lon, "beginCounty": county,
                                   "beginRoute": "US-101", "beginLocationName": "Alemany Blvd"},
                         "end": {"endLatitude": end[0], "endLongitude": end[1]}}}


CALTRANS = [caltrans_row(), caltrans_row("C2", "34.05", "-118.24", ("34.06", "-118.25"), county="Los Angeles"),
            caltrans_row("C3", "", "")]



def write_raw_dir(raw_dir: Path, rows: dict[str, list]) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    for name, recs in rows.items():
        snap = {"source": name, "layer": "x", "pulled_at": PULLED_AT, "count": len(recs), "meta": {}, "records": recs}
        (raw_dir / f"{name}.json").write_text(json.dumps(snap), encoding="utf-8")
    return raw_dir


def all_rows() -> dict[str, list]:
    return json.loads(json.dumps({
        "streets": STREETS, "street_closures": STREET_CLOSURES, "excavation_permits": EXCAVATION,
        "police_dispatch": POLICE, "chp_incidents": parse_chp(CHP_XML)[0], "caltrans_lane_closures": CALTRANS,
    }))
