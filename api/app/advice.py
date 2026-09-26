"""The transPEAKtation card's explanation, written by Gemini from the facts the planner computed.

Optional. /plan asks only when GEMINI_API_KEY is set and ml/ sent no `reasons` of its own; on no key, a slow or
failed call, or a reply that mentions a number not in the facts, the card keeps model.plan's template note.
Only trip facts are sent (times, minutes, event and street names), never coordinates or addresses.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime

import httpx

from .model import SF_TZ, fmt_clock, mins

TIMEOUT_S = 4.0
MAX_CHARS = 300
GEMINI = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
TRAFFIC = {"live": "live traffic now", "observed": "traffic recorded at that time",
           "typical": "usual traffic for that weekday and time"}
PROMPT = (
    "You write the explanation on a San Francisco trip-planning card for the recommended route. Use only the facts "
    "in the JSON: never add numbers, streets, events or times that aren't there. One or two short sentences, at "
    "most 40 words, plain text, no greeting, no emoji. Lead with what matters most for this trip: why this route "
    "(minutes saved, what it avoids), then a better departure time if one is given. Multi-day events or closures "
    "don't go away by leaving earlier or later; don't suggest that unless better_departure says so. If nothing "
    "affects the trip, say so plainly.")

_cache: dict[str, str] = {}


def model_name() -> str:
    return os.environ.get("GEMINI_MODEL", "").strip() or "gemini-flash-latest"


def _when(t: datetime) -> str:
    return f"{t.astimezone(SF_TZ):%a %b} {t.astimezone(SF_TZ).day}, {fmt_clock(t)}"


def _route(r: dict, p: dict, events: dict[str, dict]) -> dict:
    def event(h: dict) -> dict:
        ev = events.get(h["id"]) or {}
        span = f"{_when(ev['start'])} to {_when(ev['end'])}" if ev.get("start") and ev.get("end") else None
        return {"name": h["label"], "when": span}
    return {"via": r.get("summary") or None, "minutes": mins(p["dur"]),
            "minutes_added_by_events_and_closures": mins(p["delay"]) if p["delay"] >= 30 else 0,
            "events": [event(h) for h in p["event_hits"]],
            "closures_and_incidents": [i["label"] for i in p["incidents"]],
            "crosses_a_closure": p["blocked"],
            "slow_stretches": p["traffic"]["slow_segments"] if p["traffic"]["coverage"] else 0}


def facts(routes: list[dict], departs: list[datetime], mode: str, ctx: dict, result: dict) -> dict:
    """What the card can say, from model.plan's result: the pick, the fastest normal route, better departure."""
    best, preds = result["best"], result["preds"]
    events = {e["id"]: e for e in ctx.get("events") or []}
    saved = preds[0]["dur"] - preds[best]["dur"]
    adv = result.get("advice")
    return {
        "trip": {"mode": {"now": "leave now", "depart": "leave at", "arrive": "arrive by"}[mode],
                 "leave_at": _when(departs[best]), "traffic_data": TRAFFIC.get(ctx.get("traffic_kind"), "live traffic now")},
        "recommended_route": _route(routes[best], preds[best], events),
        "fastest_normal_route": _route(routes[0], preds[0], events) if best else None,
        "minutes_saved_vs_fastest_normal_route": mins(saved) if saved >= 60 else 0,
        "better_departure": {"leave_at": fmt_clock(datetime.fromisoformat(adv["depart_at"])),
                             "minutes_saved": mins(adv["saves_sec"])} if adv else None,
    }


def check(text: str, facts_json: str) -> str | None:
    """The reply, tidied, or None if it's empty, too long, or has a number the facts don't (a made-up delay/time)."""
    text = " ".join(text.split()).strip('"')
    if not text or len(text) > MAX_CHARS:
        return None
    known = set(re.findall(r"\d+", facts_json))
    return text if all(n in known for n in re.findall(r"\d+", text)) else None


async def explain(client: httpx.AsyncClient, trip: dict) -> tuple[str | None, str]:
    """(card text or None, how it was written) for data.note."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return None, "template (no GEMINI_API_KEY)"
    blob = json.dumps(trip, sort_keys=True)
    if blob in _cache:
        return _cache[blob], f"gemini:{model_name()}"
    try:
        r = await client.post(GEMINI.format(model=model_name()), headers={"x-goog-api-key": key}, timeout=TIMEOUT_S, json={
            "systemInstruction": {"parts": [{"text": PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": blob}]}],
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 1024}})
        r.raise_for_status()
        parts = r.json()["candidates"][0]["content"]["parts"]
        text = check("".join(p.get("text", "") for p in parts if not p.get("thought")), blob)
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as e:
        status = e.response.status_code if isinstance(e, httpx.HTTPStatusError) else type(e).__name__
        return None, f"template (gemini failed: {status})"
    if text is None:
        return None, "template (gemini reply rejected)"
    if len(_cache) > 500:  # ponytail: wipe-all cache, fine for one small server
        _cache.clear()
    _cache[blob] = text
    return text, f"gemini:{model_name()}"
