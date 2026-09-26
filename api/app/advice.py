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

TIMEOUT_S = 2.5  # usually 0.4-0.8 s, but some calls stall 7-30 s: those get the template
MAX_CHARS = 300
GEMINI = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
TRAFFIC = {"live": "live traffic now", "observed": "traffic recorded at that time",
           "typical": "usual traffic for that weekday and time"}
PROMPT = (
    "You write the explanation on a San Francisco trip-planning card for the recommended route. Use only the facts "
    "in the JSON: never add numbers, streets, events or times that aren't there, and write every number as digits "
    "(\"8 min\", not \"eight minutes\"). One or two short sentences, at most 40 words, plain text, no greeting, no "
    "emoji. The events and closures listed under recommended_route are ON that route: never say it avoids them, "
    "and never say how many minutes they add (no such number is given). The route avoids only what "
    "fastest_normal_route has and it doesn't. If crosses_a_closure is true, say first that the route crosses a road "
    "closure. Otherwise lead with minutes saved and what is avoided, or what is on the way. Don't give departure "
    "advice. slow_stretches are traffic, not events: with no events or closures, say there are none on the way.")
# Spelled-out numbers would slip past check()'s digit test ("one" is left out: "one slow stretch" is fine).
NUMBER_WORDS = re.compile(r"\b(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
                          r"sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|hundred)\b", re.I)

_cache: dict[str, str] = {}


def model_name() -> str:
    return os.environ.get("GEMINI_MODEL", "").strip() or "gemini-flash-lite-latest"  # ~0.5 s; thinking models took >4 s


def _when(t: datetime) -> str:
    return f"{t.astimezone(SF_TZ):%a %b} {t.astimezone(SF_TZ).day}, {fmt_clock(t)}"


def _route(r: dict, p: dict, events: dict[str, dict]) -> dict:
    def event(h: dict) -> dict:
        ev = events.get(h["id"]) or {}
        span = f"{_when(ev['start'])} to {_when(ev['end'])}" if ev.get("start") and ev.get("end") else None
        return {"name": h["label"], "when": span}
    return {"via": r.get("summary") or None, "minutes": mins(p["dur"]),
            "events_on_it": [event(h) for h in p["event_hits"]],
            "closures_and_incidents_on_it": [i["label"] for i in p["incidents"]],
            "crosses_a_closure": p["blocked"],
            "slow_stretches": p["traffic"]["slow_segments"] if p["traffic"]["coverage"] else 0}


def facts(routes: list[dict], departs: list[datetime], mode: str, ctx: dict, result: dict) -> dict:
    """What the card can say, from model.plan's result: the pick (ml/'s, or the fastest) and the fastest normal route."""
    best, preds = result["best"], result["preds"]
    events = {e["id"]: e for e in ctx.get("events") or []}
    saved = preds[0]["dur"] - preds[best]["dur"]
    return {
        "trip": {"mode": {"now": "leave now", "depart": "leave at", "arrive": "arrive by"}[mode],
                 "leave_at": _when(departs[best]), "traffic_data": TRAFFIC.get(ctx.get("traffic_kind"), "live traffic now")},
        "recommended_route": _route(routes[best], preds[best], events),
        "fastest_normal_route": _route(routes[0], preds[0], events) if best else None,
        "minutes_saved_vs_fastest_normal_route": mins(saved) if saved >= 60 else 0,
    }


def check(text: str, facts_json: str) -> str | None:
    """The reply, tidied, or None if it's empty, too long, spells a number out, or has a number the facts don't
    (a made-up delay/time)."""
    text = " ".join(text.split()).strip('"')
    if not text or len(text) > MAX_CHARS or NUMBER_WORDS.search(text):
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
