"""Shared, read-only lookups the adapters and enrichment step need."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .geo import LineIndex, StreetIndex


@dataclass
class Context:
    now: datetime
    streets: StreetIndex | None = None
    # OSM drive-graph edges keyed by Mongo road_segments.segment_id ("u-v-key"), from the GraphML
    # that `python -m pull osm_drive_graph` saves. None when the graph hasn't been pulled.
    osm: LineIndex | None = None
