"""Fetchers for the non-DataSF feeds. Each returns (records, meta) with records kept
as close to the source as possible; normalizing is the ingestion worker's job."""
from __future__ import annotations

import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .http import fetch

Records = list[dict[str, Any]]

# Covers SF incl. Treasure Island; used for Overpass queries and checks.
SF_BBOX = (-122.53, 37.69, -122.35, 37.84)  # lon_min, lat_min, lon_max, lat_max


class Skip(Exception):
    """Source can't run in this environment (missing key or optional dependency)."""


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise Skip(f"set {name} in ingest/.env")
    return value


# --- Caltrans --------------------------------------------------------------

CALTRANS_LCS_URL = "https://cwwp2.dot.ca.gov/data/d4/lcs/lcsStatusD04.json"


def caltrans_lane_closures() -> tuple[Records, dict]:
    """Caltrans District 4 (Bay Area) lane closures on state highways."""
    data = json.loads(fetch(CALTRANS_LCS_URL, timeout=120))
    return [item["lcs"] for item in data["data"]], {"url": CALTRANS_LCS_URL}


# --- CHP -------------------------------------------------------------------

CHP_URL = "https://media.chp.ca.gov/sa_xml/sa.xml"
_CHP_TOKEN = re.compile(r'<(Center|Dispatch) ID\s*=\s*"([^"]*)"|<Log ID\s*=\s*"([^"]*)">(.*?)</Log>', re.S)
_CHP_FIELD = re.compile(r'<(\w+)>"([^"]*)"</\1>')
_CHP_DETAIL = re.compile(r'<DetailTime>"([^"]*)"</DetailTime>\s*<IncidentDetail>"([^"]*)"</IncidentDetail>')


def parse_chp(xml: str) -> tuple[Records, bool]:
    """Parse CHP's incident XML. The feed is sometimes served cut off mid-file, so
    parse entry by entry and drop only the incomplete tail. Returns (records, complete)."""
    try:
        ET.fromstring(xml)
        complete = True
    except ET.ParseError:
        complete = False
    center = dispatch = None
    records = []
    for m in _CHP_TOKEN.finditer(xml):
        if m.group(1) == "Center":
            center = m.group(2)
        elif m.group(1) == "Dispatch":
            dispatch = m.group(2)
        else:
            head, _, details = m.group(4).partition("<LogDetails>")
            rec = {"log_id": m.group(3), "center": center, "dispatch": dispatch}
            rec.update(_CHP_FIELD.findall(head))
            rec["details"] = [{"time": t, "text": d} for t, d in _CHP_DETAIL.findall(details)]
            records.append(rec)
    return records, complete


def chp_incidents() -> tuple[Records, dict]:
    xml = fetch(CHP_URL).decode("utf-8", "replace")
    records, complete = parse_chp(xml)
    return records, {"url": CHP_URL, "bytes": len(xml), "complete_xml": complete}


# --- 511.org ---------------------------------------------------------------

def _511(path: str, **params: str) -> Any:
    key = _require_env("SF511_API_KEY")
    body = fetch(f"https://api.511.org{path}", params={"api_key": key, "format": "json", **params})
    return json.loads(body.decode("utf-8-sig"))  # 511 prefixes JSON with a BOM


def sf511_traffic_events() -> tuple[Records, dict]:
    """Bay Area incidents, closures, construction. Free key; ~60 requests/hour."""
    data = _511("/traffic/events")
    return data.get("events", []), {"pagination": data.get("pagination"), "meta": data.get("meta")}


def sf511_muni_vehicles() -> tuple[Records, dict]:
    """Muni vehicle positions (SIRI VehicleMonitoring, JSON)."""
    data = _511("/transit/VehicleMonitoring", agency="SF")
    delivery = data["Siri"]["ServiceDelivery"]["VehicleMonitoringDelivery"]
    if isinstance(delivery, list):
        delivery = delivery[0]
    return delivery.get("VehicleActivity", []), {"response_time": delivery.get("ResponseTimestamp")}


# --- OpenStreetMap ---------------------------------------------------------

OVERPASS_URL = "https://overpass-api.de/api/interpreter"


def osm_turn_restrictions() -> tuple[Records, dict]:
    """Turn-restriction relations (OSMnx's graph doesn't carry these)."""
    lon0, lat0, lon1, lat1 = SF_BBOX
    query = f'[out:json][timeout:180];relation["type"="restriction"]({lat0},{lon0},{lat1},{lon1});out body;'
    data = json.loads(fetch(OVERPASS_URL, data={"data": query}, timeout=240))
    return data["elements"], {"bbox": SF_BBOX, "osm_timestamp": data.get("osm3s", {}).get("timestamp_osm_base")}


EDGE_ATTRS = ("osmid", "name", "highway", "oneway", "reversed", "maxspeed", "lanes", "access", "length")


def osm_drive_graph(out_dir: Path) -> tuple[Records, dict]:
    """SF drivable road graph via OSMnx. Saves GraphML next to the snapshot and
    returns one record per edge (attributes only; geometry lives in the GraphML)."""
    try:
        import osmnx as ox
    except ImportError:
        raise Skip("needs osmnx: run with ingest/.venv (pip install -e .[osm])")
    ox.settings.cache_folder = str(out_dir.parent / "cache")
    graph = ox.graph_from_place("San Francisco, California, USA", network_type="drive")
    graphml = out_dir / "osm_drive_graph.graphml"
    ox.save_graphml(graph, graphml)
    records = [{"u": u, "v": v, "key": k, **{a: d.get(a) for a in EDGE_ATTRS}}
               for u, v, k, d in graph.edges(keys=True, data=True)]
    return records, {"nodes": graph.number_of_nodes(), "edges": graph.number_of_edges(),
                     "graphml": graphml.name, "osmnx": ox.__version__}
