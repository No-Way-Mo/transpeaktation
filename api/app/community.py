"""Community events: riders put their own events on the map (contracts/community_event.md).

Same Mongo `events` collection and doc shape as ingested events (ingest/DESIGN.md §4), `source_names: ["community"]`,
host-only fields under `sources.community`. No accounts: whoever holds an event's host key (returned once, on create;
only its SHA-256 is stored) may edit it. Promotion is only a placeholder status here: nothing is paid or verified yet.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

SOURCE = "community"
# The stored category decides the pin (web lib/context.ts KIND_BY_CATEGORY); same vocabulary as ingest's events.
CATEGORIES = ("concert", "sports", "festival", "parade", "conference", "market", "community", "other")
MAX_LENGTH = timedelta(days=7)
MAX_AHEAD = timedelta(days=365)
MAX_KEYS = 50  # My Events: at most this many events per request
# Reports: anyone can flag an event for review. Stored on their own (Mongo `event_reports`): no reporter identity, and a
# report never hides or deletes anything by itself.
REPORT_REASONS = ("doesnt_exist", "incorrect_info", "spam", "inappropriate", "other")
LOOKUP_MAX = 100  # Saved Events / shared links: at most this many ids per lookup


def _http_url(v: str | None) -> str | None:
    v = (v or "").strip()
    if not v:
        return None
    u = urlparse(v)
    if u.scheme not in ("http", "https") or not u.netloc:
        raise ValueError("must be an http(s) link")
    return v


class EventIn(BaseModel):
    """What the Add Event form sends (create and edit)."""
    title: str = Field(min_length=3, max_length=120)
    venue: str = Field(min_length=1, max_length=160, description="the place as shown to riders")
    lat: float
    lon: float
    start_time: datetime
    end_time: datetime
    category: Literal[CATEGORIES]  # type: ignore[valid-type]
    admission: Literal["free", "ticketed"]
    ticket_url: str | None = Field(None, max_length=500)
    ticket_price: float | None = Field(None, ge=0, le=10_000)
    description: str | None = Field(None, max_length=500)
    image_url: str | None = Field(None, max_length=500)

    @field_validator("title", "venue", "description")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return " ".join(v.split()) if v else v

    @field_validator("ticket_url", "image_url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        return _http_url(v)

    @field_validator("start_time", "end_time")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("needs a UTC offset")
        return v.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _consistent(self) -> "EventIn":
        if not self.end_time > self.start_time:
            raise ValueError("end_time must be after start_time")
        if self.end_time - self.start_time > MAX_LENGTH:
            raise ValueError("an event can last at most 7 days")
        if self.admission == "ticketed" and not self.ticket_url:
            raise ValueError("a ticketed event needs a ticket_url")
        if self.admission == "free":
            self.ticket_url, self.ticket_price = None, None
        return self

    def check_time(self, now: datetime) -> None:
        """Raises ValueError for an event that is already over or too far off."""
        if self.end_time <= now:
            raise ValueError("this event has already ended")
        if self.start_time > now + MAX_AHEAD:
            raise ValueError("start_time must be within a year")


class Mine(BaseModel):
    keys: dict[str, str] = Field(description="event_id -> host_key, as returned on create")

    @field_validator("keys")
    @classmethod
    def _few(cls, v: dict[str, str]) -> dict[str, str]:
        if len(v) > MAX_KEYS:
            raise ValueError(f"at most {MAX_KEYS} events")
        return v


class Report(BaseModel):
    reason: Literal[REPORT_REASONS]  # type: ignore[valid-type]
    details: str | None = Field(None, max_length=500)

    @field_validator("details")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return (" ".join(v.split()) or None) if v else None


class Lookup(BaseModel):
    ids: list[str] = Field(max_length=LOOKUP_MAX)


class HostKey(BaseModel):
    host_key: str = Field(min_length=16, max_length=128)


class Update(EventIn):
    host_key: str = Field(min_length=16, max_length=128)


def new_key() -> str:
    return secrets.token_urlsafe(24)


def key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def owns(doc: dict | None, key: str) -> bool:
    h = ((doc or {}).get("sources") or {}).get(SOURCE, {}).get("host_key_hash")
    return bool(h) and hmac.compare_digest(h, key_hash(key))


def fields(e: EventIn) -> dict[str, Any]:
    """The editable part of the Mongo doc (shared by create and edit)."""
    return {
        "title": e.title, "category": e.category, "start_time": e.start_time, "end_time": e.end_time,
        "location": {"type": "Point", "coordinates": [e.lon, e.lat]}, "venue_name": e.venue,
        f"sources.{SOURCE}.admission": e.admission, f"sources.{SOURCE}.ticket_url": e.ticket_url,
        f"sources.{SOURCE}.ticket_price": e.ticket_price, f"sources.{SOURCE}.description": e.description,
        f"sources.{SOURCE}.image_url": e.image_url,
    }


def new_doc(e: EventIn, key: str, now: datetime) -> dict[str, Any]:
    uid = uuid.uuid4().hex
    doc: dict[str, Any] = {
        "_id": "evt_" + hashlib.sha1(f"{SOURCE}:{uid}".encode()).hexdigest()[:16],  # ingest's event_id rule
        "end_is_predicted": False, "all_day": False, "venue_id": None, "capacity": None, "attendance": None,
        "status": "active", "road_closure_ids": [], "source_names": [SOURCE],
        "sources": {SOURCE: {"id": uid, "host_key_hash": key_hash(key), "promotion": {"status": "none"},
                             "created_at": now, "updated_at": now}},
        "schema_version": 1, "first_seen_at": now, "last_ingested_at": now,
    }
    for k, v in fields(e).items():  # dotted keys -> nested
        *path, last = k.split(".")
        box = doc
        for p in path:
            box = box.setdefault(p, {})
        box[last] = v
    return doc


def public(doc: dict) -> dict | None:
    """sources.community -> MapEvent.community: host-facing extras, never the key hash."""
    c = ((doc.get("sources") or {}).get(SOURCE)) if SOURCE in (doc.get("source_names") or []) else None
    if not c:
        return None
    return {"admission": c.get("admission") or "free", "ticket_url": c.get("ticket_url"),
            "ticket_price": c.get("ticket_price"), "description": c.get("description"),
            "image_url": c.get("image_url"), "promotion": {"status": (c.get("promotion") or {}).get("status") or "none"}}
