"""The normal route cards' notes (why each is slower than transPEAKtation's route), written by Gemini from the facts
the planner computed. The transPEAKtation card gets none.

Optional. /plan asks only when GEMINI_API_KEY is set and some normal route is slower; on no key, a slow or failed
call, or a reply that is too long or mentions a number not in the facts, the cards keep model.slower_note's text.
Only trip facts are sent (times, minutes, event and street names), never coordinates or addresses.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime

import httpx

from .model import NOTE_MAX, SF_TZ, fmt_clock, mins

TIMEOUT_S = 2.5  # usually 0.4-0.8 s, but some calls stall 7-30 s: those get the template
GEMINI = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
TRAFFIC = {"live": "live traffic now", "observed": "traffic recorded at that time",
           "typical": "usual traffic for that weekday and time"}
PROMPT = (
    "You write short notes for the normal route cards of a San Francisco trip-planning app. The JSON has the "
    "recommended transpeaktation_route and the normal_routes that take longer. For each normal route, in order, say "
    "why it is slower than the transPEAKtation route, in at most 90 characters: plain text, no greeting, no emoji. "
    "Use only the facts in the JSON: never add numbers, streets, events or times that aren't there, and write every "
    "number as digits (\"8 min\", not \"eight minutes\"). Name at most 2 events or closures, shortening long "
    "names. If crosses_a_closure is true, say it crosses a road closure. slow_stretches are traffic, not events. With "
    "no events, closures or slow stretches, say it is a longer or busier way. Reply with a JSON array of strings, "
    "one per normal route.")
# Spelled-out numbers would slip past check()'s digit test ("one" is left out: "one slow stretch" is fine).
NUMBER_WORDS = re.compile(r"\b(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
                          r"sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|hundred)\b", re.I)

_cache: dict[str, str] = {}


def model_name() -> str:
    return os.environ.get("GEMINI_MODEL", "").strip() or "gemini-flash-lite-latest"  # ~0.5 s; thinking models took >4 s


def _when(t: datetime) -> str:
    return f"{t.astimezone(SF_TZ):%a %b} {t.astimezone(SF_TZ).day}, {fmt_clock(t)}"


def _route(r: dict, p: dict, events: dict[str, dict], dur: float) -> dict:
    def event(h: dict) -> dict:
        ev = events.get(h["id"]) or {}
        span = f"{_when(ev['start'])} to {_when(ev['end'])}" if ev.get("start") and ev.get("end") else None
        return {"name": h["label"], "when": span}
    return {"via": r.get("summary") or None, "minutes": mins(dur),
            "events_on_it": [event(h) for h in p["event_hits"]],
            "closures_and_incidents_on_it": [i["label"] for i in p["incidents"]],
            "crosses_a_closure": p["blocked"],
            "slow_stretches": p["traffic"]["slow_segments"] if p["traffic"]["coverage"] else 0}


def facts(routes: list[dict], ctx: dict, result: dict) -> dict:
    """What the notes can say, from model.plan's result: the transPEAKtation route and each normal route with a note."""
    tp = result["preds"][result["best"]]
    events = {e["id"]: e for e in ctx.get("events") or []}
    slower = [{**_route(r, p, events, p["estimate"]["dur"]),
               "minutes_slower": mins(p["estimate"]["dur"]) - mins(tp["dur"])}
              for r, p in zip(routes, result["preds"]) if p.get("note")]
    return {"traffic_data": TRAFFIC.get(ctx.get("traffic_kind"), "live traffic now"),
            "transpeaktation_route": _route(routes[result["best"]], tp, events, tp["dur"]), "normal_routes": slower}


def check(text: str, facts_json: str) -> str | None:
    """The reply, tidied, or None if it's empty, too long, spells a number out, or has a number the facts don't
    (a made-up delay/time)."""
    text = " ".join(text.split()).strip('"')
    if not text or len(text) > NOTE_MAX or NUMBER_WORDS.search(text):
        return None
    known = set(re.findall(r"\d+", facts_json))
    return text if all(n in known for n in re.findall(r"\d+", text)) else None


async def explain(client: httpx.AsyncClient, trip: dict) -> tuple[list[str] | None, str]:
    """(one note per trip["normal_routes"], or None, how they were written) for data.note."""
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
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 1024, "responseMimeType": "application/json",
                                 "responseSchema": {"type": "ARRAY", "items": {"type": "STRING"}}}})
        r.raise_for_status()
        parts = r.json()["candidates"][0]["content"]["parts"]
        reply = json.loads("".join(p.get("text", "") for p in parts if not p.get("thought")))
        texts = [check(t, blob) if isinstance(t, str) else None for t in reply]
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as e:
        status = e.response.status_code if isinstance(e, httpx.HTTPStatusError) else type(e).__name__
        return None, f"template (gemini failed: {status})"
    if len(texts) != len(trip["normal_routes"]) or None in texts:
        return None, "template (gemini reply rejected)"
    if len(_cache) > 500:  # ponytail: wipe-all cache, fine for one small server
        _cache.clear()
    _cache[blob] = texts
    return texts, f"gemini:{model_name()}"
