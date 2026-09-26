"""Every source we pull, grouped by how often it should refresh (see TODO.md)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from datasf import DATASETS, DataSF, pull

from . import feeds

Fetch = Callable[[Path], tuple[list[dict[str, Any]], dict]]


@dataclass(frozen=True)
class Source:
    name: str
    layer: str  # "static" (nightly) | "planned" (15-60 min) | "live" (1-5 min)
    fetch: Fetch


def _datasf(key: str, layer: str) -> Source:
    ds = DATASETS[key]

    def fetch(_out_dir: Path):
        client = DataSF(timeout=120)
        return pull(client, ds), {"dataset_id": ds.id, "where": ds.where_at()}

    return Source(key, layer, fetch)


SOURCES: dict[str, Source] = {
    s.name: s
    for s in [
        Source("osm_drive_graph", "static", feeds.osm_drive_graph),
        Source("osm_turn_restrictions", "static", lambda _: feeds.osm_turn_restrictions()),
        *(_datasf(k, "static") for k in ("streets", "speed_limits", "clearance_heights",
                                         "parking_regulations", "tow_away_zones", "street_sweeping")),
        *(_datasf(k, "planned") for k in ("street_closures", "street_use_permits",
                                          "excavation_permits", "parking_signs")),
        Source("caltrans_lane_closures", "planned", lambda _: feeds.caltrans_lane_closures()),
        _datasf("police_dispatch", "live"),
        Source("sf511_traffic_events", "live", lambda _: feeds.sf511_traffic_events()),
        Source("sf511_muni_vehicles", "live", lambda _: feeds.sf511_muni_vehicles()),
        Source("chp_incidents", "live", lambda _: feeds.chp_incidents()),
    ]
}
