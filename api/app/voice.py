"""Voice → intent: ElevenLabs speech-to-text, then a small rule-based parser for trip requests.

"Plan and book my ride to Chase Center at 6:30"
  -> {action: plan_and_book, destination: "Chase Center", origin: None, time: "6:30", time_mode: "depart"}
Voice only plans. Booking / paying always needs an explicit tap in the app (AGENTS.md: voice never authorizes spending).
"""
from __future__ import annotations

import os
import re
from typing import Any

import httpx

from .providers import ProviderError

STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"
STT_MODEL = "scribe_v1"
MAX_AUDIO_BYTES = 5_000_000  # ~5 min of compressed speech; a trip request is a few seconds


def available() -> bool:
    return bool(os.environ.get("ELEVENLABS_API_KEY"))


async def transcribe(client: httpx.AsyncClient, audio: bytes, filename: str, content_type: str) -> str:
    try:
        r = await client.post(
            STT_URL,
            headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
            data={"model_id": STT_MODEL, "tag_audio_events": "false"},  # no "(laughs)" in the transcript
            files={"file": (filename, audio, content_type)},
            timeout=30,
        )
    except httpx.HTTPError as e:
        raise ProviderError(f"elevenlabs: {type(e).__name__}") from e
    if r.status_code != 200:
        raise ProviderError(f"elevenlabs: HTTP {r.status_code}")
    return (r.json().get("text") or "").strip()


# ponytail: regexes, not an LLM. Covers "X to <place> [from <place>] [at <time>]" phrasings; swap in Gemini
# (same output shape) when requests get freer-form.
_STOP = r"(?=\s+(?:from|to|at|by|around|leaving|departing|tonight|today|tomorrow|now|please)\b|[.,!?]|$)"
_TO = re.compile(r"\b(?:to|towards?)\s+(?:the\s+)?(.+?)" + _STOP, re.I)
_FROM = re.compile(r"\bfrom\s+(?:the\s+)?(.+?)" + _STOP, re.I)
_TIME = re.compile(r"\b(at|by|around)\s+(\d{1,2}(?::\d{2})?(?:\s*[ap]\.?\s?m\.?)?)", re.I)
_VERBS = {"go", "get", "be", "see", "book", "plan", "make", "take", "head", "drive", "ride", "catch", "watch", "the"}
_HERE = {"here", "my location", "current location", "my current location", "where i am"}
_PLAN_WORDS = re.compile(r"\b(plan|ride|route|trip|take me|navigate|directions|drive|go|get me|head)\b", re.I)


def _place(pattern: re.Pattern, text: str) -> str | None:
    # Last match wins, skipping infinitives: "I want to go to Oracle Park" -> "Oracle Park".
    found = [m.group(1).strip() for m in pattern.finditer(text) if m.group(1).split()[0].lower() not in _VERBS]
    return found[-1] if found else None


def parse_intent(text: str) -> dict[str, Any]:
    dest, origin = _place(_TO, text), _place(_FROM, text)
    if origin and origin.lower() in _HERE:
        origin = None  # the app's current location is already the default start
    time = _TIME.search(text)
    if re.search(r"\bbook\b", text, re.I):
        action = "plan_and_book"
    elif dest or _PLAN_WORDS.search(text):
        action = "plan"
    else:
        action = "unknown"
    return {
        "action": action, "destination": dest, "origin": origin,
        "time": time.group(2) if time else None,
        "time_mode": ("arrive" if time.group(1).lower() == "by" else "depart") if time else None,  # "by 7" = arrive by
    }
