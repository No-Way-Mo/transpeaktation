"""Coordinated routing by ml/'s load balancer: COORDINATION_URL (+ COORDINATION_API_TOKEN), HTTP only.

Optional. With COORDINATION_URL set, /plan asks it for trips that leave now: it routes on its congestion map
(ml/ forecasts it from Tiger + Mongo, once per 10 min, on demand) and spreads riders over alternatives so they don't
all pile onto the same roads. Its route becomes the transPEAKtation route, drawn with the exact roads it reserved
(never re-routed by Mapbox, which could pick other roads). Anything else (a later departure, arrive-by, a replay,
the load balancer down, slow or unable to serve the trip) keeps the ML_URL / heuristic decision and says why.

A saved trip holds a short provisional reservation (60 s) under its trip_id. The rider's app then:
    POST /trips/{trip_id}/start     {coordinated: true}  -> accept (the reservation counts for later riders)
                                    {coordinated: false} -> cancel (they took a normal route)
    POST /trips/{trip_id}/arrived                        -> complete (roads released)
    POST /trips/{trip_id}/cancel                         -> cancel
trip_id (random, returned only to the planning client) is the capability; the assignment id stays server-side.
"""
from __future__ import annotations

import math
import os
from typing import Any

import httpx

TIMEOUT_S = 12.0     # the first request after ~45 idle minutes waits for a fresh map; past this, /plan falls back
ACTION_TIMEOUT_S = 8.0


def url() -> str | None:
    return os.environ.get("COORDINATION_URL", "").strip().rstrip("/") or None


def _headers() -> dict:
    tok = os.environ.get("COORDINATION_API_TOKEN", "").strip()
    return {"Authorization": f"Bearer {tok}"} if tok else {}


async def recommend(client: httpx.AsyncClient, request_id: str, origin: tuple[float, float],
                    destination: tuple[float, float], reserve: bool) -> tuple[dict | None, str]:
    """(answer, status). answer is the load balancer's recommendation, or None with the reason in status."""
    base = url()
    if not base:
        return None, "not configured"
    body = {"request_id": request_id, "origin": list(origin), "destination": list(destination), "reserve": reserve}
    try:
        res = await client.post(f"{base}/v1/recommendations", json=body, headers=_headers(), timeout=TIMEOUT_S)
    except httpx.HTTPError as e:
        return None, f"unavailable: {type(e).__name__}"
    try:
        data = res.json()
    except ValueError:
        return None, f"unavailable: HTTP {res.status_code}"
    if res.status_code == 200 and data.get("outcome") in ("recommendation", "preview"):
        try:
            return parse(data), "ok"
        except (KeyError, TypeError, ValueError) as e:
            return None, f"off-contract answer: {e}"
    # 422 = it can't serve this trip (beyond the forecast horizon, no road nearby, no fresh map ...)
    return None, f"cannot serve this trip: {data.get('reason') or data.get('error') or res.status_code}"


def parse(data: dict) -> dict:
    """Recommendation -> {route, dur, model, reasons, assignment} for /plan. Raises on anything unusable."""
    rec = data["recommended"]
    geo = rec["geometry"]
    if geo.get("coordinate_order", "lon,lat") != "lon,lat" or len(geo["coordinates"]) < 2:
        raise ValueError("geometry must be a lon,lat line")
    dur = float(rec["forecast_eta_sec"])
    if not math.isfinite(dur) or not 0 < dur < 6 * 3600:
        raise ValueError("forecast_eta_sec out of range")
    fastest = float((data.get("fastest_candidate") or {}).get("forecast_eta_sec") or dur)
    sel = data.get("selector") or {}
    route = {
        "dur": dur, "forecast_eta_sec": dur, "dur_typical": None, "dist": float(rec["distance_m"]), "summary": "",
        "coords": [[lat, lon] for lon, lat in geo["coordinates"]],
        "congestion": None, "steps": [],       # its exact roads have no turn list; web shows the line
        "road_segment_ids": list(rec["road_segment_ids"]), "by": "ml",
    }
    a = data.get("assignment") or None
    # the selector's own reasons are codes (fastest_candidate, ...): the card gets plain words instead
    if data.get("is_fastest", True):
        reasons = ["Fastest on the forecast traffic for the next hour."]
    else:
        extra = rec.get("extra_travel_sec") or 0
        reasons = [f"Keeps riders spread off the busiest roads (+{max(1, round(extra / 60))} min vs the fastest)."]
    # its ETA sums forecast road travel times (no signals / turns), so only its ratio to its own fastest candidate is
    # comparable with the provider: /plan anchors that ratio to the provider's fastest ETA (main.py)
    return {"route": route, "dur": dur, "vs_fastest": max(1.0, dur / fastest) if fastest > 0 else 1.0,
            "model": f"coordinator-{sel.get('name', '?')}", "reasons": reasons[:3],
            "assignment": {"assignment_id": a["assignment_id"], "status": a["status"]} if a else None,
            "forecast": {k: (data.get("forecast") or {}).get(k) for k in ("issued_at", "model_version", "input_source")},
            "fallback_reason": sel.get("fallback_reason")}


async def act(client: httpx.AsyncClient, assignment_id: str, op: str) -> tuple[int, dict[str, Any]]:
    """accept | cancel | complete an assignment (no expected_version: the API owns the trip's only handle)."""
    base = url()
    if not base:
        return 503, {"error": "coordination not configured"}
    try:
        res = await client.post(f"{base}/v1/assignments/{assignment_id}/{op}", json={}, headers=_headers(),
                                timeout=ACTION_TIMEOUT_S)
        return res.status_code, res.json()
    except (httpx.HTTPError, ValueError) as e:
        return 503, {"error": f"coordination unavailable: {type(e).__name__}"}
