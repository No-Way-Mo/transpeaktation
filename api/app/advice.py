"""The normal route cards' notes: why each route might take longer than the ETA on its card ("Might take extra N
minutes due to: " + the cause, model.extra_lead), or what's on it, written by Gemini from the facts the planner computed. The transPEAKtation card gets none.

Optional. /plan asks only when GEMINI_API_KEY is set; on no key, a slow or failed call, or a reply that is too long,
spells a number out, has a number that isn't in that route's facts or names the wrong event, the cards keep
model.route_note's text.
Only trip facts are sent (minutes, event times, event and street names), never coordinates or addresses.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime

import httpx

from .model import (NOTE_MAX, SF_TZ, best_traffic, extra_lead, extra_min, fmt_clock, is_slow, mins, pick_facts, shorten,
                    slow_stretches)

log = logging.getLogger(__name__)

MAX_EVENTS = 3  # per route: PredictHQ can put 9 small ones on a downtown route, which muddles the model
TIMEOUT_S = 3.0  # 2-3 sentence notes take ~1-2 s, but some calls stall 7-30 s: those get the template
GEMINI = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
TRAFFIC = {"live": "live traffic now", "observed": "traffic recorded at that time",
           "typical": "usual traffic for that weekday and time"}
PROMPT = (
    "You write the notes on the route cards of a San Francisco trip-planning app. The JSON has the alternative "
    "routes in routes and, maybe, the route the app picked in recommended_route. Each note must fit 2 lines on a "
    "phone: 1 or 2 short sentences, 80-100 characters, never over 110. Plain text, no greeting, no emoji, no filler. "
    "Use only the facts in the JSON: never add numbers, streets, events, times or causes that aren't there, and "
    "write numbers as digits. Give the main cause and at most one more detail; leave the rest out.\n"
    "Facts per route: events_on_it (worst first; kind, when, crowd_when_you_pass = arriving or leaving or out, "
    "adds_about_min = the delay it adds), closures_and_incidents_on_it (until = when it ends), slow_stretches and "
    "slow_streets (slow traffic, not events), forecast_adds_about_min (the traffic forecast's extra delay; not an "
    "event), via.\n"
    "Alternative route notes: their cards show the usual ETA. If extra_min is given, the app puts \"Might take extra "
    "N minutes due to: \" (N = extra_min) before your note, so write only the cause, at most 70 characters, and don't "
    "repeat N. Never call a route slower, longer or busier.\n"
    "1. Main cause: crosses_a_closure true: \"Crosses the <street> road closure when you'd get there\". Else the worst "
    "event in a few words (\"Giants crowd arriving at Oracle Park\"). Else slow traffic: slow_stretches and the top "
    "slow_streets. Else the forecast if forecast_adds_about_min is given (\"heavier traffic forecast\"). Else \"No "
    "events or closures on it\".\n"
    "2. One more detail if it fits: slow streets, when the closure ends, or \"traffic flowing\" if "
    "have_traffic_data is true and slow_stretches is 0.\n"
    "Examples:\n"
    "- extra_min 10: \"Giants crowd arriving at Oracle Park; slow on King St.\"\n"
    "- \"Crosses the Howard St road closure when you'd get there; closed until 11:00 PM.\"\n"
    "- extra_min 3: \"6 slow stretches, mostly on 4th St and Bryant St.\"\n"
    "- \"Clear run via Stockton St and 4th St: no events or closures, traffic flowing.\"\n"
    "Recommended note (only if recommended_route is given): why it is the pick, same length and fact rules. Compare "
    "only with what the JSON says about the other routes; never call it the fastest.\n"
    "1. \"N min faster than the next best route.\" only if minutes_faster is given; without it never say faster, "
    "quicker or slower.\n"
    "2. avoids_a_closure_on_another_route true: \"Avoids a road closure on another route.\" Else if "
    "avoids_on_other_routes isn't empty: \"Avoids \" + the first one in a few words that keep its name. Never say "
    "avoids otherwise.\n"
    "3. If there is room, one thing it still has (worst event, slow streets, forecast), else that it's clear.\n"
    "Example: \"3 min faster than the next best route. Avoids the Giants crowd; slow only on Stockton St.\"\n"
    "Never write \"+N more\". Reply with a JSON object: {\"recommended\": string (only if recommended_route is "
    "given), \"routes\": [one string per route in routes]}.")
# Spelled-out numbers would slip past check()'s digit test ("one" is left out: "one slow stretch" is fine).
NUMBER_WORDS = re.compile(r"\b(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
                          r"sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|hundred)\b", re.I)
MINUTES = re.compile(r"(\d+)\s*(?:min|minute)", re.I)
NOT_SLOWER = re.compile(r"\b(slower|longer|busier)\b", re.I)
FASTER = re.compile(r"\b(faster|quicker|slower|shorter)\b", re.I)
AVOIDS = re.compile(r"\b(avoid|avoids|skips|dodges|bypass|bypasses)\b", re.I)

_cache: dict[str, list[str]] = {}


def model_name() -> str:
    return os.environ.get("GEMINI_MODEL", "").strip() or "gemini-3.5-flash-lite"  # fast; check with `python -m app.advice`


def _when(t: datetime) -> str:
    return f"{t.astimezone(SF_TZ):%a %b} {t.astimezone(SF_TZ).day}, {fmt_clock(t)}"


def _span(start: datetime | None, end: datetime | None) -> str | None:
    """'7:15 PM to 10:15 PM' for a one-day event; 'until Fri Oct 2, 6:00 PM' for one that runs over several."""
    if not start or not end:
        return None
    if start.astimezone(SF_TZ).date() == end.astimezone(SF_TZ).date():
        return f"{fmt_clock(start)} to {fmt_clock(end)}"
    return f"until {_when(end)}"  # a multi-day event: when it ends is what matters


STREET = [("Street", "St"), ("Avenue", "Ave"), ("Boulevard", "Blvd"), ("Drive", "Dr"), ("Road", "Rd"),
          ("Expressway", "Expy"), ("Freeway", "Fwy")]


def _short(street: str) -> str:
    for long, short in STREET:
        street = re.sub(rf"\b{long}\b", short, street)
    return street


def slow_streets(p: dict, route: dict, ctx: dict) -> list[str]:
    """The streets with the most slow traffic on the route (model.is_slow on the best row per segment), worst first."""
    if not p["traffic"]["coverage"]:
        return []
    best, names, lengths = best_traffic(ctx.get("traffic") or []), ctx.get("names") or {}, ctx.get("lengths") or {}
    slow: dict[str, float] = {}
    for sid in route.get("road_segment_ids") or []:
        if (r := best.get(sid)) and is_slow(r) and sid in names:
            slow[_short(names[sid])] = slow.get(_short(names[sid]), 0.0) + (lengths.get(sid) or 1.0)
    return sorted(slow, key=lambda n: -slow[n])[:3]


def _route(r: dict, p: dict, events: dict[str, dict], extra: int, ctx: dict) -> dict:
    def event(h: dict) -> dict:
        ev = events.get(h["id"]) or {}
        return {"name": shorten(h["label"], 50), "kind": (ev.get("category") or "event").replace("_", " "),
                "when": _span(ev.get("start"), ev.get("end")), "crowd_when_you_pass": h.get("crowd"),
                "adds_about_min": mins(h["delay"]), "passes_within_m": max(50, round(h["distance_m"] / 50) * 50)}

    def incident(i: dict) -> dict:
        until = datetime.fromisoformat(i["until"]) if i.get("until") else None
        return {"name": i["label"], "until": fmt_clock(until) if until else None}
    out = {"via": _short(r.get("summary") or "") or None,
           "events_on_it": [event(h) for h in p["event_hits"][:MAX_EVENTS]],
           "closures_and_incidents_on_it": [incident(i) for i in p["incidents"]],
           "crosses_a_closure": p["blocked"], "slow_stretches": slow_stretches(p),
           "slow_streets": slow_streets(p, r, ctx), "have_traffic_data": bool(p["traffic"]["coverage"])}
    if len(p["event_hits"]) > MAX_EVENTS:  # a busy night: the worst few, and how many more small ones
        out["smaller_events_not_listed"] = len(p["event_hits"]) - MAX_EVENTS
    if not p["event_hits"] and p["breakdown"]["events_sec"] >= 60:  # ml/'s forecast stands in for the events
        out["forecast_adds_about_min"] = mins(p["breakdown"]["events_sec"])
    if extra:
        out["extra_min"] = extra
    return out


def facts(routes: list[dict], ctx: dict, result: dict, *, pick: bool = True) -> dict:
    """What the notes can say, from model.plan's result: each normal route with a note, in order, and (pick=True)
    transPEAKtation's route, with what it avoids on the other routes (model.pick_facts)."""
    best = result["preds"][result["best"]]
    events = {e["id"]: e for e in ctx.get("events") or []}
    out = {"traffic_data": TRAFFIC.get(ctx.get("traffic_kind"), "live traffic now"),
           "routes": [_route(r, p, events, extra_min(p), ctx)
                      for r, p in zip(routes, result["preds"]) if p.get("note")]}
    if pick:
        f = pick_facts(routes, result["preds"], result["best"])
        rec = _route(routes[result["best"]], best, events, 0, ctx)
        rec["avoids_a_closure_on_another_route"] = f["avoids_a_closure"]
        rec["avoids_on_other_routes"] = [shorten(a, 50) for a in f["avoids"][:3]]
        if f["minutes_faster"]:
            rec["minutes_faster"] = f["minutes_faster"]
        out["recommended_route"] = rec
    return out


def check(text: str, route: dict) -> str | None:
    """The reply, tidied, or None if it's empty, too long (with extra_lead in front), spells a number out, has a number
    that isn't in this route's facts, gives minutes other than its event delays (made up or swapped), calls the route
    slower/longer/busier (its card shows the ETA; extra_lead says the rest), or doesn't name the route's worst
    event/closure."""
    text = _tidy(text)
    if not text or len(extra_lead(route.get("extra_min")) + text) > NOTE_MAX or NUMBER_WORDS.search(text):
        return None
    known = set(re.findall(r"\d+", json.dumps(route)))
    if not all(n in known for n in re.findall(r"\d+", text)):
        return None
    if text.lower().startswith("might take") or not _minutes_ok(text, route, None, "slower") or NOT_SLOWER.search(text):
        return None
    if not _flowing_ok(text, route):
        return None
    # It must name the worst event/closure (by a word of it), not one it made up; a blocked route just says closure.
    names = [e["name"] for e in route.get("events_on_it") or []] + \
        [i["name"] for i in route.get("closures_and_incidents_on_it") or []]
    if names and not route.get("crosses_a_closure"):
        return text if _words(names[0]) & _words(text) else None
    return text


def check_pick(text: str, rec: dict) -> str | None:
    """The recommended card's reply, tidied, or None if it breaks check()'s basic rules, gives minutes other than
    minutes_faster, calls it faster/quicker without them, claims to avoid something it doesn't, or names the wrong
    thing it avoids."""
    text = _tidy(text)
    if not text or len(text) > NOTE_MAX or NUMBER_WORDS.search(text):
        return None
    known = set(re.findall(r"\d+", json.dumps(rec)))
    if not all(n in known for n in re.findall(r"\d+", text)):
        return None
    if not _minutes_ok(text, rec, rec.get("minutes_faster"), "faster"):
        return None
    if not rec.get("minutes_faster") and FASTER.search(text):
        return None
    if not _flowing_ok(text, rec):
        return None
    avoided = rec.get("avoids_on_other_routes") or []
    if AVOIDS.search(text) and not (avoided or rec.get("avoids_a_closure_on_another_route")):
        return None
    if rec.get("avoids_a_closure_on_another_route"):
        return text if "closure" in text.lower() else None
    if avoided:
        return text if _words(avoided[0]) & _words(text) else None
    return text


def _minutes_ok(text: str, route: dict, headline: int | None, word: str) -> bool:
    """ "N min slower/faster" must be the headline number; any other "N min" one of the route's event or forecast
    delays."""
    if any(int(n) != headline for n in re.findall(rf"(\d+)\s*min(?:ute)?s?\s+{word}", text, re.I)):
        return False
    adds = {e.get("adds_about_min") for e in route.get("events_on_it") or []}
    adds |= {headline, route.get("forecast_adds_about_min")}
    return all(int(n) in adds for n in MINUTES.findall(text))


def _flowing_ok(text: str, route: dict) -> bool:
    """ "traffic flowing" only with traffic data and no slow stretches (Gemini wrote "6 slow stretches. Traffic
    flowing.")."""
    clear = route.get("have_traffic_data") and not route.get("slow_stretches")
    return bool(clear) or not re.search(r"\bflowing\b", text, re.I)


def _tidy(text: str) -> str:
    text = " ".join(text.split()).strip('"')
    return text + "." if text and text[-1] not in ".!?…" else text


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", s.lower()) if len(w) >= 4}


async def _ask(client: httpx.AsyncClient, key: str, blob: str, timeout: float):
    """Gemini's parsed JSON reply to the trip facts in `blob` (raises on HTTP errors or a reply that isn't JSON)."""
    required = ["routes", "recommended"] if '"recommended_route"' in blob else ["routes"]  # optional: it skips it
    r = await client.post(GEMINI.format(model=model_name()), headers={"x-goog-api-key": key}, timeout=timeout, json={
        "systemInstruction": {"parts": [{"text": PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": blob}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 1024, "responseMimeType": "application/json",
                             "responseSchema": {"type": "OBJECT", "required": required, "properties": {
                                 "recommended": {"type": "STRING"},
                                 "routes": {"type": "ARRAY", "items": {"type": "STRING"}}}}}})
    r.raise_for_status()
    parts = r.json()["candidates"][0]["content"]["parts"]
    return json.loads("".join(p.get("text", "") for p in parts if not p.get("thought")))


async def explain(client: httpx.AsyncClient, trip: dict) -> tuple[str | None, list[str] | None, str]:
    """(the recommended card's note or None, one note or None per trip["routes"] or None, how they were written)
    for data.note. Each note Gemini gets wrong falls back to the template on its own."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return None, None, "template (no GEMINI_API_KEY)"
    blob = json.dumps(trip, sort_keys=True)
    if blob in _cache:
        return *_cache[blob], f"gemini:{model_name()}"
    try:
        reply = await _ask(client, key, blob, TIMEOUT_S)
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as e:
        status = e.response.status_code if isinstance(e, httpx.HTTPStatusError) else type(e).__name__
        log.warning("gemini route notes failed (%s): %s", model_name(), status)
        return None, None, f"template (gemini failed: {status})"
    reply = reply if isinstance(reply, dict) else {}
    notes = reply.get("routes")
    texts = [check(t, f) if isinstance(t, str) else None for t, f in zip(notes, trip["routes"])] \
        if isinstance(notes, list) and len(notes) == len(trip["routes"]) else None  # None in it: template there
    rec = reply.get("recommended")
    pick = check_pick(rec, trip["recommended_route"]) if "recommended_route" in trip and isinstance(rec, str) else None
    texts = [t and extra_lead(f.get("extra_min")) + t for t, f in zip(texts, trip["routes"])] if texts else texts
    if texts is None or None in texts or ("recommended_route" in trip and pick is None):
        log.warning("gemini route notes rejected: %s", json.dumps(reply)[:400])
    if pick is None and not any(texts or []):
        return None, None, "template (gemini reply rejected)"
    if len(_cache) > 500:  # ponytail: wipe-all cache, fine for one small server
        _cache.clear()
    _cache[blob] = (pick, texts)
    return pick, texts, f"gemini:{model_name()}"


SAMPLE = {"traffic_data": "live traffic now", "routes": [  # what facts() sends for a trip past Oracle Park on game night
    {"via": "King St, 3rd St", "events_on_it": [
        {"name": "Giants vs. Dodgers at Oracle Park", "kind": "sports", "when": "7:15 PM to 10:15 PM",
         "crowd_when_you_pass": "arriving", "adds_about_min": 10, "passes_within_m": 150},
        {"name": "Concert at Chase Center", "kind": "concert", "when": "8:00 PM to 11:00 PM",
         "crowd_when_you_pass": "arriving", "adds_about_min": 4, "passes_within_m": 400}],
     "closures_and_incidents_on_it": [], "crosses_a_closure": False, "slow_stretches": 4,
     "slow_streets": ["King St", "3rd St"], "have_traffic_data": True, "extra_min": 10},
    {"via": "Howard St, 6th St", "events_on_it": [],
     "closures_and_incidents_on_it": [{"name": "Road closure on Howard St", "until": "11:00 PM"}],
     "crosses_a_closure": True, "slow_stretches": 0, "slow_streets": [], "have_traffic_data": True},
    {"via": "4th St, 3rd St", "events_on_it": [], "closures_and_incidents_on_it": [], "crosses_a_closure": False,
     "slow_stretches": 6, "slow_streets": ["4th St", "Bryant St"], "have_traffic_data": True, "extra_min": 3},
    {"via": "Stockton St, 4th St", "events_on_it": [], "closures_and_incidents_on_it": [], "crosses_a_closure": False,
     "slow_stretches": 0, "slow_streets": [], "have_traffic_data": True}],
    "recommended_route": {"via": "Stockton St, 4th St", "events_on_it": [], "closures_and_incidents_on_it": [],
                          "crosses_a_closure": False, "slow_stretches": 2, "slow_streets": ["Stockton St"],
                          "have_traffic_data": True, "avoids_a_closure_on_another_route": False, "minutes_faster": 3,
                          "avoids_on_other_routes": ["Giants vs. Dodgers at Oracle Park", "Concert at Chase Center"]}}


async def _live_check() -> int:
    """`python -m app.advice`: one real Gemini call on SAMPLE, with its latency, raw reply and what check() keeps."""
    import time
    from pathlib import Path

    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        print("GEMINI_API_KEY is empty in api/.env")
        return 1
    async with httpx.AsyncClient() as client:
        t = time.monotonic()
        try:
            reply = await _ask(client, key, json.dumps(SAMPLE, sort_keys=True), 30)
        except httpx.HTTPStatusError as e:
            print(f"{model_name()}: HTTP {e.response.status_code}\n{e.response.text[:800]}")
            return 1
        took = time.monotonic() - t
        print(f"{model_name()}: {took:.2f} s (/plan gives up after {TIMEOUT_S} s)")
        notes = reply.get("routes") if isinstance(reply, dict) else None
        ok = isinstance(notes, list) and len(notes) == len(SAMPLE["routes"])
        rec = reply.get("recommended") if isinstance(reply, dict) else None
        print(f"  {'kept    ' if isinstance(rec, str) and check_pick(rec, SAMPLE['recommended_route']) else 'REJECTED'}"
              f" {rec!r}  <- recommended")
        for i, route in enumerate(SAMPLE["routes"]):
            text = notes[i] if ok and isinstance(notes[i], str) else None
            print(f"  {'kept    ' if text and check(text, route) else 'REJECTED'} {text!r}")
        if not ok:
            print(f"  reply isn't one note per route: {reply!r}")
        pick, texts, how = await explain(client, SAMPLE)  # the /plan path, with its timeout
        print(f"/plan would use: {how}")
        return 0 if texts and pick else 1


if __name__ == "__main__":
    import asyncio
    raise SystemExit(asyncio.run(_live_check()))
