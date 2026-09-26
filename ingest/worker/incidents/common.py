"""Small helpers shared by adapters (deterministic keyword rules, no ML)."""
from __future__ import annotations

import re
from typing import Any

# Ordered: first match wins. Applied to upper-cased CHP LogType / police call type text.
_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("other", ("TRAFFIC STOP",)),
    ("collision", ("COLLISION", "COLLN", "ACCIDENT", "HIT AND RUN", "HIT & RUN", "HIT/RUN", "1179", "1180",
                   "1181", "1182", "1183", "20001", "20002")),
    ("closure", ("ROAD CLOSURE", "SIGALERT", "SIG ALERT", "1184")),
    ("hazard", ("HAZARD", "DEBRIS", "OBSTRUCTION", "BLOCKED", "STALL", "DISABLED", "ANIMAL", "FLOOD",
                "SPILL", "1125", "1126")),
    ("fire", ("FIRE",)),
)


def incident_category(text: Any) -> str:
    t = str(text or "").upper()
    for category, needles in _CATEGORY_RULES:
        if any(n in t for n in needles):
            return category
    return "other"


def truthy(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "y", "yes", "t")


_ABBR = {"STREET": "ST", "AVENUE": "AVE", "BOULEVARD": "BLVD", "DRIVE": "DR", "ROAD": "RD", "HIGHWAY": "HWY",
         "FREEWAY": "FWY", "INTERSTATE": "I", "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W",
         "OFFRAMP": "OFR", "ONRAMP": "ONR", "US101": "101", "I280": "280", "I80": "80", "SR1": "1"}
_STOP = {"AT", "AND", "THE", "OF", "ON", "TO", "FROM", "NEAR", "BLOCK", "SAN", "FRANCISCO", "SF", "CA", "SB",
         "NB", "EB", "WB", "N", "S", "E", "W", "ST", "AVE", "BLVD", "DR", "RD"}


def location_tokens(*texts: Any) -> frozenset[str]:
    """Street-ish tokens for conservative text matching ("I280 N / Bunker Hill" -> {280, BUNKER, HILL})."""
    out = set()
    for text in texts:
        for tok in re.findall(r"[A-Z0-9]+", str(text or "").upper()):
            tok = _ABBR.get(tok, tok)
            if tok not in _STOP and (not tok.isdigit() or len(tok) <= 3):  # keep route numbers, drop long ids
                out.add(tok)
    return frozenset(out)
