"""The route decision by ml/: POST {ML_URL}/decide (contracts/route_decision.md).

Optional. /plan asks only when ML_URL is set; when ml/ is down, slow, or answers something malformed, /plan
keeps its own heuristic pick and says why in `data.decision`.
"""
from __future__ import annotations

import math
import os
from datetime import datetime
from typing import Any

import httpx
from fastapi.encoders import jsonable_encoder

from .providers import MAX_VIA

VERSION = 1
TIMEOUT_S = 8.0
DEMAND_RADIUS_M = 400


def url() -> str | None:
    return os.environ.get("ML_URL", "").strip().rstrip("/") or None


def request_body(*, at: datetime, mode: str, replay: bool, origin: tuple[float, float],
                 destination: tuple[float, float], routes: list[dict], departs: list[datetime], ctx: dict,
                 heuristic: list[dict], demand: int | None, demand_window: tuple[datetime, datetime]) -> dict:
    """Everything /plan knows about the trip at `at`: candidate routes and the stored data for their segments."""
    return jsonable_encoder({
        "version": VERSION, "at": at, "mode": mode, "replay": replay,
        "origin": {"lon": origin[0], "lat": origin[1]}, "destination": {"lon": destination[0], "lat": destination[1]},
        "candidates": [{
            "index": i, "departs_at": d, "dur_sec": r["dur"], "dur_typical_sec": r.get("dur_typical"),
            "dist_m": r["dist"], "coords": r["coords"], "road_segment_ids": r.get("road_segment_ids") or [],
            "congestion": r.get("congestion"),
            "heuristic": {"dur_sec": h["dur"], "delay_sec": h["delay"], "breakdown": h["breakdown"], "events": h["events"],
                          "incidents": [x["label"] for x in h["incidents"]], "blocked": h["blocked"]},
        } for i, (r, d, h) in enumerate(zip(routes, departs, heuristic))],
        "context": {
            "events": ctx["events"],
            "incidents": [{k: v for k, v in x.items() if k != "_id"} for x in ctx["incidents"]],
            "traffic": {"kind": ctx["traffic_kind"], "rows": ctx["traffic"]},
            "predictions": ctx["predictions"],
            "segment_lengths_m": ctx["lengths"],
        },
        "demand": {"trips_to_destination": demand, "radius_m": DEMAND_RADIUS_M, "window": list(demand_window)},
    })


def parse(body: Any, n_candidates: int, in_area) -> dict:
    """ml/'s answer -> {model, dur, reasons, best | waypoints}. Raises ValueError on anything off-contract."""
    if not isinstance(body, dict) or not isinstance(body.get("model"), str) or not body["model"]:
        raise ValueError("needs a model name")
    dur = body.get("predicted_sec")
    if not isinstance(dur, (int, float)) or isinstance(dur, bool) or not math.isfinite(dur) or not 0 < dur < 6 * 3600:
        raise ValueError("predicted_sec must be seconds, > 0")
    reasons = body.get("reasons") or []
    if not isinstance(reasons, list) or not all(isinstance(r, str) for r in reasons):
        raise ValueError("reasons must be a list of strings")
    out = {"model": body["model"][:60], "dur": float(dur), "reasons": [r[:200] for r in reasons[:3]]}
    choice = body.get("choice")
    if isinstance(choice, dict) and "candidate" in choice:
        i = choice["candidate"]
        if not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < n_candidates:
            raise ValueError(f"choice.candidate must be 0..{n_candidates - 1}")
        return {**out, "best": i}
    if isinstance(choice, dict) and "waypoints" in choice:
        wps = choice["waypoints"]
        if not isinstance(wps, list) or not 1 <= len(wps) <= MAX_VIA:
            raise ValueError(f"choice.waypoints must be 1..{MAX_VIA} [lon, lat] points")
        try:
            pts = [(float(lon), float(lat)) for lon, lat in wps]
        except (TypeError, ValueError):
            raise ValueError("choice.waypoints must be [lon, lat] pairs") from None
        if not all(in_area(p) for p in pts):
            raise ValueError("choice.waypoints must be inside the service area")
        return {**out, "waypoints": pts}
    raise ValueError("choice must be {candidate: i} or {waypoints: [[lon, lat], ...]}")


async def decide(client: httpx.AsyncClient, body: dict, n_candidates: int, in_area) -> tuple[dict | None, str]:
    """(decision, status). decision is None when ml/ isn't configured or its answer can't be used."""
    base = url()
    if not base:
        return None, "heuristic"
    try:
        res = await client.post(f"{base}/decide", json=body, timeout=TIMEOUT_S)
        res.raise_for_status()
        return parse(res.json(), n_candidates, in_area), "ml"
    except (httpx.HTTPError, ValueError) as e:  # down, slow, 5xx, not JSON, off-contract: keep the heuristic
        return None, f"heuristic (ml unavailable: {type(e).__name__}: {str(e)[:100]})"
