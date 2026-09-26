"""The DataSF feeds Transpeaktation cares about, plus time helpers.

Socrata "floating" timestamps carry no offset. On DataSF they are San Francisco
local time, except columns explicitly named *_utc.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .client import DataSF

SF_TZ = ZoneInfo("America/Los_Angeles")
HORIZON = timedelta(days=30)  # how far ahead to pull planned closures/permits


@dataclass(frozen=True)
class Dataset:
    key: str
    id: str
    name: str
    why: str
    time_field: str | None = None  # when the thing happens; None for static reference data
    # SoQL filter for routing-relevant rows. {now} and {horizon} (now + HORIZON) are
    # filled in the dataset's own time zone.
    where: str | None = None
    time_is_utc: bool = False
    id_field: str | tuple[str, ...] | None = None  # natural key (may be composite), for dedupe checks
    geo_field: str | None = None

    def where_at(self, now: datetime | None = None) -> str | None:
        if not self.where:
            return None
        now = now or datetime.now(timezone.utc)
        return (self.where
                .replace("{now}", soql_ts(now, is_utc=self.time_is_utc))
                .replace("{horizon}", soql_ts(now + HORIZON, is_utc=self.time_is_utc)))


DATASETS: dict[str, Dataset] = {
    d.key: d
    for d in [
        # Static road rules
        Dataset("streets", "3psu-pn9h", "Streets - Active and Retired",
                "SF street network keyed by cnn, with one-way flags",
                where="active = true", id_field="cnn", geo_field="line"),
        Dataset("speed_limits", "3t7b-gebn", "Speed Limits per Street Segment",
                "Posted and school-zone limits per segment",
                id_field="objectid", geo_field="shape"),
        Dataset("clearance_heights", "eb2x-6eay", "Clearance Heights - Bridges and Underpasses",
                "Low clearances for tall vehicles", id_field="objectid", geo_field="shape"),
        Dataset("parking_regulations", "hi6h-neyh", "Parking Regulations",
                "Curb rules that decide where pickup/drop-off is legal",
                id_field="objectid", geo_field="shape"),
        Dataset("tow_away_zones", "ynvq-waab", "Regularly Scheduled Tow-Away Zones",
                "Peak-hour lanes that clear of parked cars", id_field="towsegid", geo_field="geometry"),
        Dataset("street_sweeping", "yhqp-riqs", "Street Sweeping Schedule",
                "Scheduled curb-lane loss", id_field="blocksweepid", geo_field="line"),
        # Planned closures and permits
        Dataset("street_closures", "8x25-yybr", "Temporary Street Closures",
                "Planned closures incl. special events -> hard routing constraints",
                time_field="start_utc", where="end_utc >= '{now}'", time_is_utc=True,
                id_field="objectid", geo_field="shape"),
        Dataset("street_use_permits", "b6tj-gt35", "Street-Use Permits",
                "Construction and curb use that narrows roads",
                time_field="permit_start_date",
                where="permit_end_date >= '{now}' AND permit_start_date <= '{horizon}'"
                      " AND status not in ('VOID', 'WITHDRAW', 'DENIED', 'CANCELLED')",
                id_field="unique_identifier", geo_field="the_geom"),
        Dataset("excavation_permits", "smdf-6c45", "Utility Excavation Permits",
                "Utility digs; located by cnn only (no geometry). One row per permit per segment",
                time_field="effective_date",
                where="expiration_date >= '{now}' AND effective_date <= '{horizon}'",
                id_field=("permit_number", "cnn")),
        Dataset("parking_signs", "sftu-nd43", "Parking Signs / Street Space Permits",
                "Temporary no-parking signs (moves, filming, construction)",
                time_field="datetimeentered", id_field=("signid", "cnn", "sideofstreet"),
                geo_field="location_2"),
        # Live
        Dataset("police_dispatch", "gnap-fj3t", "Law Enforcement Dispatched Calls: Real-Time",
                "Live incidents, ~20 min lag, last ~12 h",
                time_field="received_datetime", id_field="id", geo_field="intersection_point"),
        # Not pulled; ~1 day lag, keep/drop still undecided (see TODO.md)
        Dataset("fire_ems", "nuek-vuh3", "Fire Dept & EMS Dispatched Calls",
                "Incidents that block lanes (daily batch)", time_field="received_dttm"),
        Dataset("sf311_street", "vw6y-z8j6", "311 Cases (street-related)",
                "Blocked streets and road defects (daily batch)", time_field="requested_datetime",
                where="service_name in ('Blocked Street and Sidewalk', 'Street Defect')"),
        Dataset("traffic_crashes", "ubvf-ztfx", "Traffic Crashes Resulting in Injury",
                "Crash history (released ~2 months late)", time_field="collision_datetime"),
        Dataset("police_incidents", "wg3w-h783", "Police Incident Reports (2018+)",
                "Filed reports (daily batch)", time_field="incident_datetime"),
    ]
}


def parse_ts(value: str | None, *, is_utc: bool = False) -> datetime | None:
    """Socrata floating timestamp -> aware UTC datetime."""
    if not value:
        return None
    dt = datetime.fromisoformat(value.rstrip("Z"))
    return dt.replace(tzinfo=timezone.utc if is_utc else SF_TZ).astimezone(timezone.utc)


def soql_ts(dt: datetime, *, is_utc: bool = False) -> str:
    """Aware datetime -> floating timestamp literal in the column's own zone."""
    return dt.astimezone(timezone.utc if is_utc else SF_TZ).strftime("%Y-%m-%dT%H:%M:%S")


def latest(client: DataSF, ds: Dataset, n: int = 1, *, not_after: datetime | None = None) -> list[dict[str, Any]]:
    """Most recent n rows by the dataset's time field (ignores future-dated rows)."""
    if not ds.time_field:
        raise ValueError(f"{ds.key} is static reference data with no time field")
    not_after = not_after or datetime.now(timezone.utc)
    clauses = [f"{ds.time_field} <= '{soql_ts(not_after, is_utc=ds.time_is_utc)}'"]
    if ds.where:
        clauses.append(f"({ds.where_at(not_after)})")
    return client.query(ds.id, where=" AND ".join(clauses), order=f"{ds.time_field} DESC", limit=n)


def pull(client: DataSF, ds: Dataset, *, now: datetime | None = None, page_size: int = 50_000) -> list[dict[str, Any]]:
    """Every routing-relevant row of a dataset (its `where` filter applied)."""
    return list(client.iter_rows(ds.id, where=ds.where_at(now), page_size=page_size))


def active_street_closures(client: DataSF, at: datetime | None = None, *, limit: int = 5000) -> list[dict[str, Any]]:
    """Closures in effect at `at` (default: now). Each row carries a `shape` LineString."""
    t = soql_ts(at or datetime.now(timezone.utc), is_utc=True)
    return list(client.iter_rows(
        DATASETS["street_closures"].id,
        where=f"start_utc <= '{t}' AND end_utc >= '{t}'",
        order="start_utc, objectid",
        max_rows=limit,
    ))
