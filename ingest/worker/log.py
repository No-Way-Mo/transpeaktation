"""Structured logging: one JSON object per line on stderr (or key=value text)."""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

LOGGER = logging.getLogger("worker")
LOGGER.addHandler(logging.NullHandler())  # silent until setup() (e.g. in tests)
LOGGER.propagate = False


class _Formatter(logging.Formatter):
    def __init__(self, fmt: str):
        super().__init__()
        self.fmt = fmt

    def format(self, record: logging.LogRecord) -> str:
        fields: dict[str, Any] = getattr(record, "fields", {})
        ts = datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        if self.fmt == "json":
            return json.dumps({"ts": ts, "level": record.levelname.lower(), "event": record.getMessage(), **fields},
                              default=str, ensure_ascii=False)
        kv = " ".join(f"{k}={v}" for k, v in fields.items())
        return f"{ts} {record.levelname:<7} {record.getMessage()} {kv}".rstrip()


def setup(fmt: str = "json", level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_Formatter(fmt))
    LOGGER.handlers[:] = [handler]
    LOGGER.setLevel(level)
    LOGGER.propagate = False


def event(name: str, level: int = logging.INFO, **fields: Any) -> None:
    LOGGER.log(level, name, extra={"fields": fields})
