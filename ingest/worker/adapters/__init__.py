"""Source -> normalizer registry. Every source the worker reads has an entry:
a normalizer `(raw_row, Context) -> Record | list[Record] | None` (None / [] = filtered,
e.g. outside the Bay Area) or an 'unsupported' reason reported instead of guessing.

Snapshot sources come from pull.sources.SOURCES (data/raw/<name>.json). Time-series
sources are the extra files other pull commands append (TIMESERIES)."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from pull.poll import TS_DIR
from pull.sources import SOURCES

from ..context import Context
from ..records import Record
from . import datasf_sources, feeds, mapbox

Normalizer = Callable[[dict, Context], "Record | list[Record] | None"]

NORMALIZERS: dict[str, Normalizer] = {**datasf_sources.NORMALIZERS, **feeds.NORMALIZERS, **mapbox.NORMALIZERS}
UNSUPPORTED: dict[str, str] = dict(feeds.UNSUPPORTED)
REQUIRES_OSM: dict[str, str] = dict(mapbox.REQUIRES_OSM)

# name -> (layer, directory of *.jsonl files, one raw row per line)
TIMESERIES: dict[str, tuple[str, Path]] = {mapbox.SOURCE: ("live", TS_DIR)}

LAYERS: dict[str, str] = {**{n: s.layer for n, s in SOURCES.items()}, **{n: v[0] for n, v in TIMESERIES.items()}}
