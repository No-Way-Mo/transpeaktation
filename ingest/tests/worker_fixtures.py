"""Small raw snapshots in the exact shape `python -m pull` writes, for worker tests."""
from __future__ import annotations

import copy
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

SPEED_LIMITS = [
    {"objectid": "1", "cnn": "100", "speedlimit": "25", "shape": STREETS[0]["line"]},
    {"objectid": "2", "cnn": "200", "speedlimit": "0", "shape": None},
    {"objectid": "3", "cnn": "300", "speedlimit": "99"},
    {"objectid": "4", "cnn": "100", "speedlimit": "fast"},
]

CLEARANCE = [{"objectid": "1", "shape": {"type": "Point", "coordinates": [-122.4195, 37.77005]}}]

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

PARKING_SIGNS = [
    {"signid": "5", "cnn": "100", "sideofstreet": "N", "startdate": "09/25/2026", "enddate": "09/27/2026",
     "datetimeentered": "2026-09-24T09:00:00.000", "location_2": {"latitude": "37.7701", "longitude": "-122.4195"}},
    {"signid": "5", "cnn": "200", "sideofstreet": "S", "startdate": "09/25/2026", "enddate": "09/27/2026",
     "location_2": {"latitude": "", "longitude": ""}},
    {"signid": "6", "cnn": "100", "sideofstreet": "N", "startdate": "bad", "enddate": "09/27/2026"},
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

OSM_EDGES = [
    {"u": 1, "v": 2, "key": 0, "osmid": 11, "name": "Market Street", "highway": "primary", "oneway": True,
     "reversed": False, "maxspeed": "25 mph", "lanes": "2", "access": None, "length": 88.4},
    {"u": 2, "v": 3, "key": 0, "osmid": [12, 13], "name": None, "highway": "residential", "oneway": False,
     "reversed": [False, True], "maxspeed": ["40", "30 mph"], "lanes": None, "access": None, "length": 50},
    {"u": 2, "v": 1, "key": 0, "osmid": 11, "name": "Market Street", "highway": "primary", "oneway": False,
     "reversed": True, "maxspeed": "25 mph", "lanes": "2", "access": None, "length": 88.4},
    {"u": 3, "v": 2, "key": 0, "osmid": 12, "name": None, "highway": "residential", "oneway": False,
     "reversed": False, "maxspeed": None, "lanes": None, "access": None, "length": 50},
]

GRAPHML = '''<?xml version='1.0' encoding='utf-8'?>
<graphml xmlns="http://graphml.graphdrawing.org/xmlns">
<key id="d4" for="node" attr.name="y" attr.type="string"/><key id="d5" for="node" attr.name="x" attr.type="string"/>
<key id="d9" for="edge" attr.name="geometry" attr.type="string"/>
<graph edgedefault="directed">
<node id="1"><data key="d4">37.77</data><data key="d5">-122.42</data></node>
<node id="2"><data key="d4">37.77</data><data key="d5">-122.419</data></node>
<node id="3"><data key="d4">37.771</data><data key="d5">-122.419</data></node>
<edge source="1" target="2" id="0"><data key="d9">LINESTRING (-122.42 37.77, -122.4195 37.7701, -122.419 37.77)</data></edge>
<edge source="2" target="3" id="0"/>
<edge source="2" target="1" id="0"><data key="d9">LINESTRING (-122.419 37.77, -122.4195 37.7701, -122.42 37.77)</data></edge>
<edge source="3" target="2" id="0"/>
</graph></graphml>'''

TURNS = [{"type": "relation", "id": 7, "tags": {"type": "restriction", "restriction": "no_left_turn"},
          "members": [{"type": "way", "ref": 11, "role": "from"}, {"type": "node", "ref": 2, "role": "via"},
                      {"type": "way", "ref": 12, "role": "to"}]},
         {"type": "relation", "id": 8, "tags": {}, "members": [{"type": "way", "ref": 1, "role": "from"}]}]


MARKET_EAST = [[-122.42, 37.77], [-122.4195, 37.7701], [-122.419, 37.77]]


def mapbox_row(direction="ab", coords=MARKET_EAST, polled_at="2026-09-26T00:40:00+00:00", ok=True, **seg):
    n = len(coords) - 1
    segments = {"distance_m": [44.2] * n, "duration_s": [10.0] * n, "speed_mps": [4.42] * n,
                "congestion": ["moderate"] * n, "congestion_numeric": [40] * n, "maxspeed": [{"unknown": True}] * n}
    segments.update(seg)
    row = {"polled_at": polled_at, "corridor": "market", "direction": direction, "ok": ok}
    if ok:
        row.update(duration_s=10.0 * n, duration_typical_s=8.0 * n, distance_m=44.2 * n, segments=segments,
                   geometry=coords)
    else:
        row["error"] = "503 from https://api.mapbox.com/directions"
    return row


MAPBOX_POLLS = [
    mapbox_row("ab"),
    mapbox_row("ba", coords=MARKET_EAST[::-1]),
    mapbox_row(ok=False),
    mapbox_row(duration_s=[10.0]),                                       # arrays disagree -> quarantined
    mapbox_row(coords=[[-122.45, 37.75], [-122.4495, 37.7501]]),         # no OSM edge nearby -> filtered
]


def write_timeseries(ts_dir: Path, polls=None) -> Path:
    ts_dir.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(p) for p in (MAPBOX_POLLS if polls is None else polls)]
    (ts_dir / "2026-09-26.jsonl").write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    return ts_dir


def rows() -> dict[str, list]:
    return copy.deepcopy({
        "streets": STREETS, "speed_limits": SPEED_LIMITS, "clearance_heights": CLEARANCE,
        "street_closures": STREET_CLOSURES, "excavation_permits": EXCAVATION, "parking_signs": PARKING_SIGNS,
        "police_dispatch": POLICE, "chp_incidents": parse_chp(CHP_XML)[0], "caltrans_lane_closures": CALTRANS,
        "osm_drive_graph": OSM_EDGES, "osm_turn_restrictions": TURNS,
    })


def write_raw_dir(raw_dir: Path, only: list[str] | None = None, *, manifest: dict | None = None) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    for name, recs in rows().items():
        if only and name not in only:
            continue
        meta = {"graphml": "osm_drive_graph.graphml"} if name == "osm_drive_graph" else {}
        snap = {"source": name, "layer": "x", "pulled_at": PULLED_AT, "count": len(recs), "meta": meta,
                "records": recs}
        (raw_dir / f"{name}.json").write_text(json.dumps(snap), encoding="utf-8")
    if not only or "osm_drive_graph" in only:
        (raw_dir / "osm_drive_graph.graphml").write_text(GRAPHML, encoding="utf-8")
    (raw_dir / "_manifest.json").write_text(json.dumps(manifest or {
        "sf511_traffic_events": {"status": "skip", "reason": "set SF511_API_KEY in ingest/.env"},
        "sf511_muni_vehicles": {"status": "skip", "reason": "set SF511_API_KEY in ingest/.env"},
    }), encoding="utf-8")
    return raw_dir
