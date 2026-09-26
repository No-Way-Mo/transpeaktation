"""The normalized record every adapter produces, plus ids and serialization."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

from .timeutil import iso

SCHEMA_VERSION = 1
KINDS = ("road_segment", "road_rule", "closure", "incident", "traffic_metric")

# How a record got its location.
LOCATION_STATUSES = (
    "exact",         # geometry from the source itself
    "from_cnn",      # geometry looked up from the SF street network by cnn
    "geocoded",      # geometry from a geocoder (text address)
    "network_ref",   # no geometry; located by OSM node/way ids
    "withheld",      # the source deliberately hides the location (e.g. sensitive police calls)
    "unlocated",     # source gave no usable location and nothing could resolve it
)


class RecordError(ValueError):
    """A single raw row can't be turned into a record (it goes to quarantine)."""


def make_id(source: str, source_id: str) -> str:
    """Deterministic id: re-running ingestion upserts the same entity."""
    return f"{source}:{source_id}"


def natural_key(row: dict, fields: str | Iterable[str]) -> str:
    """Natural (possibly composite) key as a string; composite parts joined with '|'."""
    fields = (fields,) if isinstance(fields, str) else tuple(fields)
    parts = []
    for f in fields:
        v = row.get(f)
        if v in (None, ""):
            raise RecordError(f"missing natural key field {f!r}")
        parts.append(str(v).strip())
    return "|".join(parts)


@dataclass
class Record:
    kind: str
    source: str
    source_id: str
    geometry: dict | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    observed_at: datetime | None = None
    road_ref: dict[str, Any] | None = None   # {"cnn": str, "match": segment|intersection|nearest_segment|unknown, ...}
    road_segment_ids: list[str] = field(default_factory=list)  # Mongo road_segments.segment_id (OSM "u-v-key")
    # Joins actually computed this run ("cnn", "speed_limit", "road_segment_ids"). Upserts only
    # $set joined fields that were computed, so a run without the street/OSM data doesn't blank them.
    computed: set[str] = field(default_factory=set)
    location_status: str = "exact"
    source_fields: dict[str, Any] = field(default_factory=dict)
    geocode_query: str | None = None         # text address to geocode when there is no location
    layer: str | None = None                 # set by the pipeline from pull.sources
    pulled_at: datetime | None = None        # set by the pipeline from the snapshot
    also_reported_by: list[dict[str, str]] = field(default_factory=list)

    @property
    def id(self) -> str:
        return make_id(self.source, self.source_id)

    def provenance(self) -> dict[str, Any]:
        return {"source": self.source, "source_id": self.source_id, "pulled_at": self.pulled_at,
                "also_reported_by": self.also_reported_by}


def _default(o: Any) -> Any:
    if isinstance(o, datetime):
        return iso(o)
    if isinstance(o, (set, tuple)):
        return list(o)
    raise TypeError(f"not JSON serializable: {type(o).__name__}")


def dumps(obj: Any, **kw: Any) -> str:
    return json.dumps(obj, default=_default, ensure_ascii=False, **kw)


def clean_source_fields(row: dict, drop: Iterable[str] = ()) -> dict[str, Any]:
    """Raw row minus geometry columns and Socrata ':@computed_region_*' noise."""
    drop = set(drop)
    return {k: v for k, v in row.items() if k not in drop and not k.startswith(":")}
