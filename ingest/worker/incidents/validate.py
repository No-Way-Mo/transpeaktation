"""Per-record validation. Returns a list of problems; empty means the record is storable."""
from __future__ import annotations

from datetime import timezone

from .geom import GeometryError, normalize_geometry
from .records import KINDS, LOCATION_STATUSES, Record

_UNLOCATABLE = ("withheld", "unlocated")


def validate(r: Record) -> list[str]:
    errors: list[str] = []
    if r.kind not in KINDS:
        errors.append(f"unknown kind {r.kind!r}")
    if not r.source or not r.source_id:
        errors.append("missing source / source_id")
    if r.location_status not in LOCATION_STATUSES:
        errors.append(f"unknown location_status {r.location_status!r}")
    if r.geometry is not None:
        try:
            if normalize_geometry(r.geometry) != r.geometry:
                errors.append("geometry not normalized")
        except GeometryError as e:
            errors.append(f"geometry: {e}")
    for name in ("valid_from", "valid_to", "observed_at"):
        dt = getattr(r, name)
        if dt is not None and (dt.tzinfo is None or dt.utcoffset() != timezone.utc.utcoffset(None)):
            errors.append(f"{name} is not UTC-aware")
    if r.valid_from and r.valid_to and r.valid_to < r.valid_from:
        errors.append("valid_to before valid_from")
    has_location = r.geometry is not None or bool(r.road_ref and r.road_ref.get("cnn"))
    if r.kind == "closure":
        if r.valid_from is None and r.valid_to is None:
            errors.append("closure needs a start or end time")
        if not has_location:
            errors.append("closure has no location (no geometry, no cnn)")
    elif r.kind == "incident":
        if r.observed_at is None:
            errors.append("incident needs observed_at")
        if not has_location and r.location_status not in _UNLOCATABLE:
            errors.append("incident has no location and is not marked withheld/unlocated")
    return errors
