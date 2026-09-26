"""Event-aware trip model: candidate routes + what the databases know -> predicted time per route, pick, why.

Pure functions (no I/O), so the planner is testable offline. Stand-in until ml/ writes prediction_metrics;
when forecasts exist for a route's segments they replace the event heuristic below.

Event impact (CLAUDE.md "Hackathon MVP", interpretable on purpose):
    delay = size_factor(attendance or capacity) x type_factor x time_factor x distance_factor
      size_factor     1.25 * sqrt(people / 1000) min, clamped to 2..12 (Oracle ~41k -> 8 min, Chase ~18k -> 5 min)
      time_factor     1 while the crowd arrives [start-90, start+15] or leaves [end-15, end+60], ramping over 30 min
      distance_factor 1 within 200 m of the venue, fading to 0 at 700 m, at the moment the route passes it
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
NOT_A_DELAY = {"street_use_permit", "excavation"}  # permits narrow curbs/lanes; not counted as delay
LIVE_WINDOW = timedelta(minutes=30)  # observed traffic only says something about trips starting soon
DESTINATION_M = 400  # a route ending this close to a venue is a trip to that event
MPH = 0.44704  # m/s


# --- events ------------------------------------------------------------------------------------------------

def event_size(ev: dict) -> float:
    return float(ev.get("attendance") or ev.get("capacity") or 3000)


def event_max_delay_s(ev: dict) -> float:
    minutes = min(12.0, max(2.0, 1.25 * math.sqrt(event_size(ev) / 1000)))
    return minutes * 60 * TYPE_FACTOR.get(ev.get("category") or "", 0.7)


def crowd_windows(ev: dict) -> list[tuple[datetime, datetime]]:
    """When the crowd is on the streets. Events with no fixed start (markets, fairs) count for their whole span."""
    start, end = ev["start"], ev.get("end")
    if ev.get("all_day") or (end and end - start >= timedelta(hours=5)):
        return [(start, end or start + timedelta(hours=6))]
    end = end or start + DEFAULT_LENGTH.get(ev.get("category") or "", timedelta(hours=2))
    return [(start - ARRIVE_BEFORE, start + ARRIVE_AFTER), (end - LEAVE_BEFORE, end + LEAVE_AFTER)]


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
    """Seconds added by events the route passes while their crowd is out, and which events."""
    coords, dur = route["coords"], route["dur"]
    total, hits = 0.0, []
    for ev in events:
        k, d = min(((i, meters(c, (ev["lat"], ev["lon"]))) for i, c in enumerate(coords)), key=lambda x: x[1])
        near = distance_factor(d)
        if not near:
            continue
        passing = depart + timedelta(seconds=dur * k / max(1, len(coords) - 1))
        s = event_max_delay_s(ev) * near * time_factor(passing, crowd_windows(ev))
        if s >= MIN_EVENT_DELAY_S:
            total += s
            hits.append({"id": ev["id"], "label": f"{ev['title']} at {ev['venue']}", "delay": round(s),
                         "impact": round(100 * s / (12 * 60)), "distance_m": round(d)})
    return total, hits


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
    return (s is None or s <= t) and (e is None or t <= e)


def incident_label(inc: dict) -> str:
    d = inc.get("details") or {}
    where = d.get("name") or d.get("street") or d.get("location_text") or d.get("route") or "your route"
    kind = "Road closure" if inc.get("is_closure") else (d.get("call_type") or inc.get("category") or "Incident")
    return f"{kind} on {where}".replace("_", " ")


def incident_effects(incidents: list[dict], segment_ids: list[str], arrivals: list[datetime]) -> tuple[float, list[dict]]:
    """Closures/incidents that are active on a route segment at the moment the trip reaches it."""
    pos = {s: i for i, s in reversed(list(enumerate(segment_ids)))}  # first time the route uses each segment
    delay, minor, out = 0.0, 0.0, []
    for inc in incidents:
        if inc.get("category") in NOT_A_DELAY:
            continue
        idx = min((pos[s] for s in inc.get("road_segment_ids") or [] if s in pos), default=None)
        if idx is None or not _active(inc, arrivals[idx]):
            continue
        blocked = bool(inc.get("is_closure"))
        if blocked:
            delay += CLOSURE_PENALTY_S
        else:
            minor += INCIDENT_DELAY_S
        out.append({"label": incident_label(inc), "is_closure": blocked, "source": inc.get("source"),
                    "at": arrivals[idx].isoformat(), "until": inc["end_time"].isoformat() if inc.get("end_time") else None})
    return delay + min(minor, INCIDENT_CAP_S), out


def traffic_effect(rows: list[dict], segment_ids: list[str], lengths: list[float] | None) -> dict:
    """Observed speed vs free flow on the route (best source per segment). delay_sec = extra time now."""
    from .store import TRAFFIC_SOURCES

    rank = {s: i for i, s in enumerate(TRAFFIC_SOURCES)}
    best: dict[str, dict] = {}
    for r in rows:
        cur = best.get(r["road_segment_id"])
        if cur is None or rank.get(r["source"], 9) < rank.get(cur["source"], 9):
            best[r["road_segment_id"]] = r
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
        slow += (r.get("congestion_ratio") or 0) >= 0.5
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
    return t.astimezone(SF_TZ).strftime("%-I:%M %p")


def mins(s: float) -> int:
    return max(1, round(s / 60))


def departure_advice(route: dict, depart: datetime, mode: str, ctx: dict, *, now: datetime, current: float) -> dict | None:
    """A better departure for the picked route, if moving it by up to 90 min saves 5+ minutes."""
    if mode == "arrive":
        return None
    # Heading to an event? Only suggest times that still get you there before it starts.
    going_to = [e["start"] for e in ctx.get("events") or []
                if meters(route["coords"][-1], (e["lat"], e["lon"])) <= DESTINATION_M and e["start"] > depart]
    latest_arrival = min(going_to) if going_to else None
    best_t, best_dur = None, current
    for off in range(-45, 91, 15):
        t = depart + timedelta(minutes=off)
        if off == 0 or t < now - timedelta(minutes=1):
            continue
        d = predict_route(route, t, ctx, now=now)["dur"]
        if latest_arrival and t + timedelta(seconds=d) > latest_arrival:
            continue
        if d < best_dur - 1:
            best_t, best_dur = t, d
    if best_t is None or current - best_dur < 300:
        return None
    saves = current - best_dur
    return {"depart_at": best_t.isoformat(), "saves_sec": round(saves),
            "text": f"Leaving at {fmt_clock(best_t)} saves ~{mins(saves)} min."}


def plan(routes: list[dict], departs: list[datetime], mode: str, ctx: dict, *, now: datetime) -> dict:
    """transPEAKtation's pick: lowest predicted time. Same shape as web's former client-side transPeakPick."""
    preds = [predict_route(r, d, ctx, now=now) for r, d in zip(routes, departs)]
    best = min(range(len(preds)), key=lambda i: preds[i]["dur"])
    p, first = preds[best], preds[0]
    saved, extra = first["dur"] - p["dur"], p["delay"]
    why_first = first["events"] + [i["label"] for i in first["incidents"]]
    why_best = p["events"] + [i["label"] for i in p["incidents"]]
    advice = departure_advice(routes[best], departs[best], mode, ctx, now=now, current=p["dur"])
    if all(x["blocked"] for x in preds):
        tag, note = "Closure ahead", f"Every route crosses a closure when you'd get there: {', '.join(why_best)}."
    elif saved >= 60:
        tag, note = f"Saves ~{mins(saved)} min", f"Skips {' and '.join(why_first) or 'slower traffic'} on the fastest route."
    elif extra >= 30:
        tag, note = f"+{mins(extra)} min events", f"Includes ~{mins(extra)} min for {' and '.join(why_best) or 'traffic'}."
        if not advice:
            note += " Leaving earlier or later helps."
    else:
        tag, note = "Clear", "No events or closures on your way at this time."
    if advice:
        note += f" {advice['text']}"
    if p["traffic"]["coverage"] and p["traffic"]["slow_segments"]:
        note += f" Live traffic: {p['traffic']['slow_segments']} slow stretch{'es' if p['traffic']['slow_segments'] > 1 else ''} on this route."
    return {"best": best, "preds": preds, "tag": tag, "note": note, "advice": advice}


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
