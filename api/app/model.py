"""Event-aware trip model: candidate routes + what the databases know -> predicted time per route, pick, why.

Pure functions (no I/O), so the planner is testable offline. Stand-in until ml/ writes prediction_metrics;
when forecasts exist for a route's segments they replace the event heuristic below.

Event impact (CLAUDE.md "Hackathon MVP", interpretable on purpose):
    delay = tier_delay x time_factor x distance_factor
      tier            crowd = (attendance or capacity) x type_factor: high >= 15k (Oracle, Chase) +10 min,
                      medium >= 5k +5 min, low (incl. unknown size) +2 min
      time_factor     1 while the crowd arrives [start-90, start+15] or leaves [end-15, end+60], ramping over 30 min
      distance_factor 1 within 200 m of the venue, fading to 0 at 700 m, at the moment the route passes it
    A route gets its worst event's delay, not the sum: crowds along one route overlap, and a dozen small
    conferences shouldn't add up to more than a ballgame.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence
from zoneinfo import ZoneInfo

SF_TZ = ZoneInfo("America/Los_Angeles")
MIN_EVENT_DELAY_S = 30
TYPE_FACTOR = {"concert": 1.0, "sports": 1.0, "festival": 1.0, "parade": 1.0, "community": 0.9,
               "performing_arts": 0.7, "conference": 0.6, "holiday": 0.5}
ARRIVE_BEFORE, ARRIVE_AFTER = timedelta(minutes=90), timedelta(minutes=15)
LEAVE_BEFORE, LEAVE_AFTER = timedelta(minutes=15), timedelta(minutes=60)
RAMP = timedelta(minutes=30)
DEFAULT_LENGTH = {"sports": timedelta(hours=3), "concert": timedelta(hours=3)}

CLOSURE_PENALTY_S = 20 * 60    # a road closed when you get there: effectively blocked, rank it last
INCIDENT_DELAY_S = 90          # crash / hazard / lane closure active when you pass
INCIDENT_CAP_S = 5 * 60
# ponytail: fixed clearance guess for incidents with no end time (crashes, dispatch calls), the same 3 h as
# contracts/map_context.schema.json's point-event rule; ingest closing them when they leave their feed would be exact.
OPEN_ENDED = timedelta(hours=3)
NOT_A_DELAY = {"street_use_permit", "excavation"}  # permits narrow curbs/lanes; not counted as delay
LIVE_WINDOW = timedelta(minutes=30)  # observed traffic only says something about trips starting soon
MPH = 0.44704  # m/s


# --- events ------------------------------------------------------------------------------------------------

def event_size(ev: dict) -> float:
    return float(ev.get("attendance") or ev.get("capacity") or 3000)


TIER_MIN = {"low": 2, "medium": 5, "high": 10}  # minutes an event adds at full crowd, right by the venue


def event_tier(ev: dict) -> str:
    crowd = event_size(ev) * TYPE_FACTOR.get(ev.get("category") or "", 0.7)
    return "high" if crowd >= 15_000 else "medium" if crowd >= 5_000 else "low"


def event_max_delay_s(ev: dict) -> float:
    return TIER_MIN[event_tier(ev)] * 60.0


def crowd_windows(ev: dict) -> list[tuple[datetime, datetime]]:
    """When the crowd is on the streets. Events with no fixed start (markets, fairs) count for their whole span."""
    start, end = ev["start"], ev.get("end")
    if ev.get("all_day") or (end and end - start >= timedelta(hours=5)):
        return [(start, end or start + timedelta(hours=6))]
    end = end or start + DEFAULT_LENGTH.get(ev.get("category") or "", timedelta(hours=2))
    return [(start - ARRIVE_BEFORE, start + ARRIVE_AFTER), (end - LEAVE_BEFORE, end + LEAVE_AFTER)]


def crowd_phase(t: datetime, windows: list[tuple[datetime, datetime]]) -> str:
    """Which crowd you'd meet at t: arriving (the window before the start) or leaving; all-day events: out."""
    if len(windows) == 1:
        return "out"
    gap = lambda w: timedelta(0) if w[0] <= t <= w[1] else min(abs(t - w[0]), abs(t - w[1]))  # noqa: E731
    return "arriving" if gap(windows[0]) <= gap(windows[1]) else "leaving"


def time_factor(t: datetime, windows: list[tuple[datetime, datetime]]) -> float:
    best = 0.0
    for a, b in windows:
        if a <= t <= b:
            return 1.0
        gap = min(abs(t - a), abs(t - b))
        best = max(best, 1 - gap / RAMP)
    return max(0.0, best)


def distance_factor(m: float) -> float:
    return min(1.0, max(0.0, (700 - m) / 500))


def meters(a: Sequence[float], b: Sequence[float]) -> float:
    """[lat, lon] pairs."""
    dy = (a[0] - b[0]) * 111_132
    dx = (a[1] - b[1]) * 111_320 * math.cos(math.radians((a[0] + b[0]) / 2))
    return math.hypot(dx, dy)


def event_effects(route: dict, depart: datetime, events: list[dict]) -> tuple[float, list[dict]]:
    """Seconds added by events the route passes while their crowd is out (the worst one's), and which events,
    worst first."""
    coords, dur = route["coords"], route["dur"]
    hits = []
    for ev in events:
        k, d = min(((i, meters(c, (ev["lat"], ev["lon"]))) for i, c in enumerate(coords)), key=lambda x: x[1])
        near = distance_factor(d)
        if not near:
            continue
        passing = depart + timedelta(seconds=dur * k / max(1, len(coords) - 1))
        windows = crowd_windows(ev)
        s = event_max_delay_s(ev) * near * time_factor(passing, windows)
        if s >= MIN_EVENT_DELAY_S:
            label = ev["title"] if ev["venue"] == ev["title"] else f"{ev['title']} at {ev['venue']}"  # DataSF: venue = title
            hits.append({"id": ev["id"], "label": label, "delay": round(s),
                         "impact": event_tier(ev), "distance_m": round(d), "crowd": crowd_phase(passing, windows)})
    hits.sort(key=lambda h: -h["delay"])
    return (hits[0]["delay"] if hits else 0.0), hits


# --- road segments: closures, traffic, forecasts ---------------------------------------------------------

def segment_arrivals(segment_ids: list[str], lengths: list[float] | None, depart: datetime, dur: float) -> list[datetime]:
    """When the trip reaches the start of each segment, spreading the route's duration by segment length."""
    n = len(segment_ids)
    if not n:
        return []
    w = lengths if lengths and len(lengths) == n and sum(lengths) > 0 else [1.0] * n
    total, walked, out = sum(w), 0.0, []
    for x in w:
        out.append(depart + timedelta(seconds=dur * walked / total))
        walked += x
    return out


def _active(inc: dict, t: datetime) -> bool:
    s, e = inc.get("start_time"), inc.get("end_time")
    if e is None and s is not None:
        e = s + OPEN_ENDED
    return (s is None or s <= t) and (e is None or t <= e)


def incident_label(inc: dict) -> str:
    d = inc.get("details") or {}
    where = d.get("name") or d.get("street") or d.get("location_text") or d.get("route") or "your route"
    kind = "Road closure" if inc.get("is_closure") else (d.get("call_type") or inc.get("category") or "Incident")
    return f"{kind} on {where}".replace("_", " ")


def incident_effects(incidents: list[dict], segment_ids: list[str], arrivals: list[datetime]) -> tuple[float, list[dict]]:
    """Closures/incidents that are active on a route segment at the moment the trip reaches it."""
    pos = {s: i for i, s in reversed(list(enumerate(segment_ids)))}  # first time the route uses each segment
    minor, out, seen = 0.0, [], set()
    for inc in incidents:
        if inc.get("category") in NOT_A_DELAY:
            continue
        idx = min((pos[s] for s in inc.get("road_segment_ids") or [] if s in pos), default=None)
        if idx is None or not _active(inc, arrivals[idx]):
            continue
        blocked, label = bool(inc.get("is_closure")), incident_label(inc)
        if (label, blocked) in seen:  # sources list one closure per direction/block: count it once
            continue
        seen.add((label, blocked))
        minor += 0 if blocked else INCIDENT_DELAY_S
        out.append({"label": label, "is_closure": blocked, "source": inc.get("source"),
                    "at": arrivals[idx].isoformat(), "until": inc["end_time"].isoformat() if inc.get("end_time") else None})
    # A closure makes the route blocked (one penalty, however many closures); minor incidents add up to a cap.
    return (CLOSURE_PENALTY_S if any(i["is_closure"] for i in out) else 0) + min(minor, INCIDENT_CAP_S), out


def best_traffic(rows: list[dict]) -> dict[str, dict]:
    """segment_id -> its row from the most trusted source (store.TRAFFIC_SOURCES order)."""
    from .store import TRAFFIC_SOURCES

    rank = {s: i for i, s in enumerate(TRAFFIC_SOURCES)}
    best: dict[str, dict] = {}
    for r in rows:
        cur = best.get(r["road_segment_id"])
        if cur is None or rank.get(r["source"], 9) < rank.get(cur["source"], 9):
            best[r["road_segment_id"]] = r
    return best


def is_slow(r: dict) -> bool:
    return (r.get("congestion_ratio") or 0) >= 0.5


def traffic_effect(rows: list[dict], segment_ids: list[str], lengths: list[float] | None) -> dict:
    """Observed speed vs free flow on the route (best source per segment). delay_sec = extra time now."""
    best = best_traffic(rows)
    length = dict(zip(segment_ids, lengths)) if lengths and len(lengths) == len(segment_ids) else {}
    delay = observed = total = 0.0
    slow, newest, sources = 0, None, set()
    for sid in segment_ids:
        L = length.get(sid) or 0.0
        total += L
        r = best.get(sid)
        if not r:
            continue
        ff = r.get("free_flow_speed_mph") or 25.0
        speed = r.get("speed_mph")
        if speed is None and r.get("congestion_ratio") is not None:
            speed = ff * (1 - r["congestion_ratio"])
        if speed is None:
            continue
        speed = max(speed, 3.0)
        observed += L
        delay += max(0.0, L / (speed * MPH) - L / (ff * MPH))
        slow += is_slow(r)
        sources.add(r["source"])
        newest = max(newest, r["time"]) if newest else r["time"]
    return {"delay_sec": round(delay), "slow_segments": slow, "coverage": round(observed / total, 2) if total else 0.0,
            "as_of": newest.isoformat() if newest else None, "sources": sorted(sources)}


def forecast_delay(rows: list[dict], segment_ids: list[str], arrivals: list[datetime]) -> tuple[float, str] | None:
    """ml/'s predicted delay along the route at arrival time, or None when there are no forecasts for it."""
    by_seg: dict[str, list[dict]] = {}
    for r in rows:
        by_seg.setdefault(r["road_segment_id"], []).append(r)
    total, models = 0.0, set()
    for sid, t in zip(segment_ids, arrivals):
        cands = by_seg.get(sid)
        if cands:
            r = min(cands, key=lambda x: abs(x["time"] - t))
            total += r.get("predicted_delay_sec") or 0.0
            models.add(r.get("model_version") or "?")
    return (total, ",".join(sorted(models))) if models else None


# --- the plan ----------------------------------------------------------------------------------------------

def predict_route(route: dict, depart: datetime, ctx: dict, *, now: datetime) -> dict:
    """ctx: events, incidents, traffic rows, predictions, lengths per segment_id (any may be empty)."""
    sids = route.get("road_segment_ids") or []
    lengths = [ctx["lengths"].get(s, 0.0) for s in sids] if ctx.get("lengths") else None
    arrivals = segment_arrivals(sids, lengths, depart, route["dur"])
    fc = forecast_delay(ctx.get("predictions") or [], sids, arrivals)
    if fc:
        ev_s, ev_hits, model = fc[0], [], f"ml:{fc[1]}"
    else:
        ev_s, ev_hits = event_effects(route, depart, ctx.get("events") or [])
        model = "event-impact heuristic v1"
    inc_s, incidents = incident_effects(ctx.get("incidents") or [], sids, arrivals)
    traffic = traffic_effect(ctx.get("traffic") or [], sids, lengths)
    # Mapbox ETAs already include live traffic; OSRM's don't, so add what our sensors see (trips starting soon).
    traffic_s = traffic["delay_sec"] if route.get("dur_typical") is None and abs(depart - now) <= LIVE_WINDOW else 0
    delay = ev_s + inc_s + traffic_s
    return {"dur": route["dur"] + delay, "delay": round(delay), "events": [h["label"] for h in ev_hits],
            "breakdown": {"events_sec": round(ev_s), "incidents_sec": round(inc_s), "traffic_sec": round(traffic_s)},
            "event_hits": ev_hits, "incidents": incidents, "traffic": traffic, "model": model,
            "blocked": any(i["is_closure"] for i in incidents)}


def fmt_clock(t: datetime) -> str:
    t = t.astimezone(SF_TZ)
    return f"{t.hour % 12 or 12}:{t:%M %p}"  # not %-I: Windows strftime rejects it


def mins(s: float) -> int:
    return max(1, round(s / 60))


def plan(routes: list[dict], departs: list[datetime], mode: str, ctx: dict, *, now: datetime,
         ml: dict | None = None) -> dict:
    """The transPEAKtation card. Its route and time are ml/'s decision (app/ml.py: best, dur, model, reasons);
    without one, the provider's fastest route and ETA, unchanged: api/ doesn't re-pick or re-time routes.
    preds carry what is on each route (events, closures, stored traffic) for the explanation, and api/'s own
    event-impact `estimate`, which web shows on the normal routes ("longer than it looks") and ml/ gets as
    `heuristic` (main.py); it never changes the transPEAKtation pick or time."""
    preds = [{**x, "dur": r["dur"], "delay": 0, "model": "provider ETA",
              "estimate": {"dur": x["dur"], "delay": x["delay"], "why": x["events"] + [i["label"] for i in x["incidents"]]}}
             for r, x in zip(routes, (predict_route(r, d, ctx, now=now) for r, d in zip(routes, departs)))]
    best = ml["best"] if ml else 0
    if ml:
        preds[best] = {**preds[best], "dur": ml["dur"], "delay": round(ml["dur"] - routes[best]["dur"]),
                       "model": f"ml:{ml['model']}"}
    p, first = preds[best], preds[0]
    saved = first["dur"] - p["dur"]
    tag = ("Closure ahead" if p["blocked"] else f"Saves ~{mins(saved)} min" if saved >= 60
           else "Events on the way" if p["events"] or p["incidents"] else "Clear")
    # Normal cards: the congestion on each when you'd drive it. transPEAKtation's card: why this pick (ml/'s reasons
    # when it gave some). Gemini rewords both (main.py).
    tp_min = mins(p["dur"])
    for r, x in zip(routes, preds):
        if r.get("by") == "ml":  # ml/'s own route is never shown as a normal route
            continue
        x["note"] = route_note(x, minutes_slower(x, tp_min))
    note = " ".join(ml["reasons"]) if ml and ml.get("reasons") else pick_note(pick_facts(routes, preds, best))
    return {"best": best, "preds": preds, "tag": tag, "note": note, "advice": None}


def pick_facts(routes: list[dict], preds: list[dict], best: int) -> dict:
    """What transPEAKtation's card can claim, against the *other* normal routes only (without ml/, the pick is
    normal route `best` itself), comparing api/'s estimates on both sides so the minutes are like for like."""
    p = preds[best]
    others = [x for i, (r, x) in enumerate(zip(routes, preds)) if i != best and r.get("by") != "ml"]
    own = set(p["estimate"]["why"])
    avoids = list(dict.fromkeys(w for x in others for w in x["estimate"]["why"] if w not in own))
    # a closed route's estimate is mostly CLOSURE_PENALTY_S: "avoids a road closure" covers it, not the minutes
    open_ = [x for x in others if not x["blocked"]]
    faster = min((mins(x["estimate"]["dur"]) for x in open_), default=0) - mins(p["estimate"]["dur"])
    return {"on_it": p["estimate"]["why"], "blocked": p["blocked"], "slow_stretches": slow_stretches(p),
            "have_traffic_data": bool(p["traffic"]["coverage"]), "avoids": avoids,
            "avoids_a_closure": not p["blocked"] and any(x["blocked"] for x in others),
            "minutes_faster": faster if open_ and faster > 0 else 0}


def pick_note(f: dict) -> str:
    """transPEAKtation's card: why this route, in at most NOTE_MAX characters. Claims only what pick_facts found."""
    out = []
    if f["minutes_faster"]:
        out.append(f"{f['minutes_faster']} min faster than the next best route.")
    if f["avoids_a_closure"]:
        out.append("Avoids a road closure on another route.")
    elif f["avoids"]:
        more = f" +{len(f['avoids']) - 1} more" if len(f["avoids"]) > 1 else ""
        out.append(f"Avoids {shorten(f['avoids'][0], 40)}{more}.")
    if f["blocked"]:
        out.append("Crosses a road closure when you'd get there.")
    elif f["on_it"]:
        out.append(f"Passes {shorten(f['on_it'][0], 40)}.")
    elif f["slow_stretches"]:
        out.append(f"{f['slow_stretches']} slow stretch{'es' if f['slow_stretches'] > 1 else ''} on the way.")
    elif not out:
        out.append("No events or closures on it." + (" Traffic is flowing." if f["have_traffic_data"] else ""))
    text = " ".join(out).replace("….", "…")
    return text if len(text) <= NOTE_MAX else shorten(text, NOTE_MAX)


NOTE_MAX = 110  # 2 lines on a phone or the desktop sidebar; Gemini aims for 80-100


def minutes_slower(x: dict, tp_min: int) -> int:
    """How many whole minutes a normal route's estimate is over the transPEAKtation card's time (0 if not)."""
    return max(0, mins(x["estimate"]["dur"]) - tp_min)


def slow_stretches(x: dict) -> int:
    return x["traffic"]["slow_segments"] if x["traffic"]["coverage"] else 0


def route_note(x: dict, slower: int) -> str:
    """The congestion on a normal route when you'd drive it, led by how many minutes it is slower than
    transPEAKtation's (if it is), in at most NOTE_MAX characters."""
    if x["blocked"]:  # its minutes are mostly CLOSURE_PENALTY_S, not a real delay: no number
        return "Crosses a road closure when you'd get there."
    why, slow = x["estimate"]["why"], slow_stretches(x)  # why: worst event first, then closures/incidents
    stretches = f"{slow} slow stretch{'es' if slow > 1 else ''}"
    if why:
        body = shorten(why[0], 45) + (f" +{len(why) - 1} more" if len(why) > 1 else "") + (f", {stretches}" if slow else "")
    elif slow:
        body = f"{stretches} of traffic"
    else:
        body = "longer or busier roads" if slower else "no events or closures on it"
    text = f"{slower} min slower: {body}" if slower else body[0].upper() + body[1:]
    return text if text.endswith("…") else text + "."


def shorten(text: str, n: int) -> str:
    """At most n characters, cut at a word ("Catawba and Cherokee American…"), never mid-word."""
    return text if len(text) <= n else text[:n - 1].rsplit(" ", 1)[0].rstrip(",;:-") + "…"


# --- events: database docs, demo fallback, web view ----------------------------------------------------------

def from_mongo(e: dict) -> dict | None:
    loc = (e.get("location") or {}).get("coordinates")
    if not loc or not e.get("start_time"):
        return None
    v = e.get("venue") or {}
    return {"id": str(e["_id"]), "title": e.get("title") or "Event", "category": e.get("category"),
            "venue": v.get("name") or e.get("title") or "Venue", "keys": v.get("keys") or [],
            "lat": loc[1], "lon": loc[0], "start": e["start_time"], "end": e.get("end_time"),
            "attendance": e.get("attendance"), "capacity": e.get("capacity") or v.get("capacity"),
            "drop": v.get("drop_off"), "source": "mongo"}


def from_map_event(e: dict) -> dict:
    """A MapEvent (store.find_closure_events: DataSF special-event closures) -> the planner's event shape."""
    end = e.get("end_time")
    return {"id": e["id"], "title": e["name"], "category": e.get("category"), "venue": e.get("venue") or e["name"],
            "keys": [], "lat": e["lat"], "lon": e["lon"], "start": datetime.fromisoformat(e["start_time"]),
            "end": datetime.fromisoformat(end) if end else None, "source": e["source"]}


def demo_events(day: datetime) -> list[dict]:
    """The design's three demo events on `day` (SF local), used until ingest writes Mongo `events`."""
    d = day.astimezone(SF_TZ).date()
    at = lambda h, m: datetime(d.year, d.month, d.day, h, m, tzinfo=SF_TZ)  # noqa: E731
    return [
        {"id": "demo-oracle", "title": "Giants vs. Dodgers", "category": "sports", "venue": "Oracle Park",
         "keys": ["oracle", "giants", "ballpark"], "lat": 37.7786, "lon": -122.3893, "start": at(19, 15),
         "end": at(22, 15), "capacity": 41265, "source": "demo",
         "drop": {"label": "drop-off at 4th & King", "lat": 37.7765, "lon": -122.3942,
                  "why": "Skips the King St backup. 5 min walk to the gate."}},
        {"id": "demo-chase", "title": "Concert", "category": "concert", "venue": "Chase Center",
         "keys": ["chase", "warriors", "mission bay"], "lat": 37.768, "lon": -122.3877, "start": at(20, 0),
         "end": at(23, 0), "capacity": 18064, "source": "demo",
         "drop": {"label": "drop-off at 16th & 3rd St", "lat": 37.7665, "lon": -122.389,
                  "why": "Avoids the Warriors Way curb queue. 3 min walk."}},
        {"id": "demo-ferry", "title": "Farmers market", "category": "community", "venue": "Ferry Building",
         "keys": ["ferry", "farmers market", "embarcadero"], "lat": 37.7955, "lon": -122.3937, "start": at(8, 0),
         "end": at(14, 0), "capacity": 8000, "source": "demo",
         "drop": {"label": "drop-off at Washington & Embarcadero", "lat": 37.7962, "lon": -122.3972,
                  "why": "Keeps you out of market-day curb traffic. 4 min walk."}},
    ]


def event_view(ev: dict) -> dict:
    """What web/lib/suggest.ts renders: local clock times, the main crowd window, a drop-off if one is curated."""
    win = crowd_windows(ev)[0]
    hm = lambda t: [t.astimezone(SF_TZ).hour, t.astimezone(SF_TZ).minute]  # noqa: E731
    fixed = len(crowd_windows(ev)) > 1
    delay = mins(event_max_delay_s(ev))
    out = {"id": ev["id"], "venue": ev["venue"], "keys": ev.get("keys") or [], "title": ev["title"],
           "time": fmt_clock(ev["start"]) if fixed else f"until {fmt_clock(win[1])}",
           "start": hm(ev["start"]) if fixed else None, "lat": ev["lat"], "lon": ev["lon"],
           "crowd": {"from": hm(win[0]), "to": hm(win[1]), "delay": delay}, "source": ev.get("source")}
    if ev.get("drop"):
        out["drop"] = {**ev["drop"], "badge": f"Saves ~{delay} min"}
    return out
