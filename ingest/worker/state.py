"""Worker state kept on disk next to the data it describes (ingest/data/worker/).

state.json   per-source watermarks + the latest TomTom free flow per segment / relative per line
lines_<feed>.json   provider line key -> [[segment_id, metres], ...], reset when the OSM graph changes
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from pull import INGEST_DIR

STATE_DIR = INGEST_DIR / "data" / "worker"


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)  # atomic: a crash never leaves half a state file


class State:
    def __init__(self, directory: Path = STATE_DIR):
        self.dir = directory
        self.path = directory / "state.json"
        d = _read(self.path, {})
        self.watermarks: dict[str, str] = d.get("watermarks", {})
        self.tomtom_free_flow: dict[str, float] = d.get("tomtom_free_flow", {})       # segment_id -> mph
        self.tomtom_relative: dict[str, list] = d.get("tomtom_relative", {})          # line key -> [ratio, iso]
        self.meta: dict[str, Any] = d.get("meta", {})

    def watermark(self, source: str) -> datetime | None:
        v = self.watermarks.get(source)
        return datetime.fromisoformat(v) if v else None

    def set_watermark(self, source: str, t: datetime) -> None:
        self.watermarks[source] = t.isoformat()

    def save(self) -> None:
        _write(self.path, {"watermarks": self.watermarks, "tomtom_free_flow": self.tomtom_free_flow,
                           "tomtom_relative": self.tomtom_relative, "meta": self.meta})


class LineMaps:
    """Cache of provider line -> OSM segments. Tile feeds reuse the same few thousand lines
    every poll, so each line is snapped once, not once per poll."""

    def __init__(self, directory: Path, feed: str, graph_sig: str):
        self.path = directory / f"lines_{feed}.json"
        d = _read(self.path, {})
        self.graph_sig = graph_sig
        self.map: dict[str, list] = d.get("map", {}) if d.get("graph_sig") == graph_sig else {}
        self.dirty = False

    def get(self, key: str) -> list | None:
        return self.map.get(key)

    def put(self, key: str, value: list) -> None:
        self.map[key] = value
        self.dirty = True

    def save(self) -> None:
        if self.dirty:
            _write(self.path, {"graph_sig": self.graph_sig, "map": self.map})
            self.dirty = False
