"""Timestamp normalization. Everything leaves here as an aware UTC datetime.

Source rules (see TODO.md "Data notes"):
- DataSF: floating timestamps are SF local, except columns named *_utc.
- DataSF date-only columns (parking signs) are SF-local calendar days.
- CHP: "Sep 25 2026  5:59PM", Pacific local.
- Caltrans: unix epoch seconds (strings); "" / "0" mean unknown.
"""
from __future__ import annotations

import math
from datetime import datetime, time, timedelta, timezone
from typing import Any

from datasf.datasets import SF_TZ, parse_ts


def to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError(f"naive datetime {dt.isoformat()} (zone unknown)")
    return dt.astimezone(timezone.utc)


def datasf_ts(field: str, value: Any) -> datetime | None:
    """A DataSF timestamp column, zone chosen by the documented column convention."""
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field}: expected timestamp string, got {type(value).__name__}")
    return parse_ts(value, is_utc=field.endswith("_utc"))


def local_day(value: Any, *, end: bool = False, fmt: str = "%m/%d/%Y") -> datetime | None:
    """SF-local calendar day -> UTC start of that day (or start of the next day when end=True)."""
    if value in (None, ""):
        return None
    day = datetime.strptime(str(value).strip(), fmt).date()
    if end:
        day += timedelta(days=1)
    return datetime.combine(day, time(), tzinfo=SF_TZ).astimezone(timezone.utc)


def chp_ts(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    local = datetime.strptime(" ".join(str(value).split()), "%b %d %Y %I:%M%p")
    return local.replace(tzinfo=SF_TZ).astimezone(timezone.utc)


def epoch(value: Any) -> datetime | None:
    """Unix epoch (seconds, or milliseconds when obviously so) -> UTC. Blank/0 -> None."""
    if value in (None, ""):
        return None
    secs = float(value)
    if not math.isfinite(secs) or secs <= 0:
        return None
    if secs > 1e11:  # milliseconds
        secs /= 1000
    return datetime.fromtimestamp(secs, timezone.utc)


def iso(dt: datetime | None) -> str | None:
    return None if dt is None else to_utc(dt).isoformat().replace("+00:00", "Z")
