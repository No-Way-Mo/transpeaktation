"""Turn-by-turn steps for a route we made ourselves (ml/'s load balancer), in the provider's step shape
(providers._step), so web's directions list, highlighted turns and phone navigation work unchanged.

Built from the route's own data: its OSM road segments in driving order and its exact line. The junction between
two consecutive segments is their shared OSM node (app/segments.py gives its position in the drive graph's metre
grid); it is located on the route line, and the turn there is the change of heading along the line just before vs.
just after it. Consecutive segments on one street are one step; a step starts where the street name changes or the
road turns by TURN_SPLIT_DEG or more. Unnamed pieces (short connectors) belong to the street before them.
Simpler than a provider's guidance: plain turns and street names, no lanes, forks, ramps or roundabouts.
"""
from __future__ import annotations

import math

TURN_SPLIT_DEG = 60      # same street name but the road turns this much: still a step (e.g. a street's corner)
HEADING_M = (20, 50)     # headings over these many metres before / after a junction; the bigger change wins
                         # (the long one catches a ramp that curves off a street before its junction)
MAX_JOINT_OFF_M = 30     # a junction farther than this from the line: the pieces don't line up, no directions
CARDINAL = ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"]


class _Line:
    """The route line in metres (xy, parallel to its [lat, lon] coords)."""

    def __init__(self, xy, coords):
        self.xy, self.c = xy, coords
        self.cum = [0.0]
        for a, b in zip(xy, xy[1:]):
            self.cum.append(self.cum[-1] + math.dist(a, b))
        self.length = self.cum[-1]

    def _find(self, d: float) -> tuple[int, float]:
        d = min(max(d, 0.0), self.length)
        i = next((k for k in range(1, len(self.cum)) if self.cum[k] >= d), len(self.cum) - 1)
        seg = self.cum[i] - self.cum[i - 1]
        return i, 0.0 if seg <= 0 else (d - self.cum[i - 1]) / seg

    def xy_at(self, d: float):
        i, f = self._find(d)
        a, b = self.xy[i - 1], self.xy[i]
        return a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f

    def lonlat_at(self, d: float) -> list[float]:
        i, f = self._find(d)
        a, b = self.c[i - 1], self.c[i]
        return [a[1] + (b[1] - a[1]) * f, a[0] + (b[0] - a[0]) * f]

    def heading(self, d0: float, d1: float) -> float | None:
        """Compass heading (degrees clockwise from north; the grid's +y is north) from d0 to d1."""
        (x0, y0), (x1, y1) = self.xy_at(d0), self.xy_at(d1)
        return None if math.hypot(x1 - x0, y1 - y0) < 1 else math.degrees(math.atan2(x1 - x0, y1 - y0)) % 360

    def locate(self, p, after: float) -> tuple[float, float]:
        """(distance along the line of the point nearest p, at or after `after`; its distance from p)."""
        best = (after, math.inf)
        for k in range(1, len(self.xy)):
            if self.cum[k] < after:
                continue
            (ax, ay), (bx, by) = self.xy[k - 1], self.xy[k]
            dx, dy = bx - ax, by - ay
            L2 = dx * dx + dy * dy
            t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
            d = self.cum[k - 1] + t * (self.cum[k] - self.cum[k - 1])
            off = math.hypot(ax + t * dx - p[0], ay + t * dy - p[1])
            if d >= after and off < best[1]:
                best = (d, off)
        return best


def modifier(delta: float) -> str:
    """Heading change (degrees, + = clockwise) -> the provider's maneuver modifier."""
    a, side = abs(delta), "right" if delta > 0 else "left"
    if a < 25:
        return "straight"
    if a < 50:
        return f"slight {side}"
    if a < 135:
        return side
    return f"sharp {side}" if a < 170 else "uturn"


def build(coords: list[list[float]], xy: list, joints: list, segment_ids: list[str], names: dict[str, str],
          duration_s: float) -> list[dict]:
    """coords: the route's [lat, lon] line and xy the same points in the drive graph's metres; joints: the xy of the
    node where segment k ends and k+1 begins (len(segment_ids) - 1 of them). [] when the pieces don't line up:
    no directions beats wrong ones."""
    if len(coords) < 2 or len(xy) != len(coords) or len(joints) != len(segment_ids) - 1:
        return []
    line = _Line(xy, coords)
    if line.length <= 0:
        return []
    at, after = [0.0], 0.0
    for p in joints:
        d, off = line.locate(p, after)
        if off > MAX_JOINT_OFF_M:
            return []
        at.append(d)
        after = d

    def turn(d: float) -> float:
        deltas = [0.0]
        for w in HEADING_M:
            h0, h1 = line.heading(d - w, d), line.heading(d, d + w)
            if h0 is not None and h1 is not None:
                deltas.append((h1 - h0 + 540) % 360 - 180)
        return max(deltas, key=abs)

    first = names.get(segment_ids[0], "")
    h = line.heading(0, HEADING_M[0])
    steps = [(0.0, first, "depart", CARDINAL[round(h / 45) % 8] if h is not None else None)]
    street = first
    for s, d0 in zip(segment_ids[1:], at[1:]):
        name = names.get(s, "")
        delta = turn(d0)
        if not (name and name != street) and abs(delta) < TURN_SPLIT_DEG:
            continue                            # same street (or an unnamed connector) going on
        name = name or street
        mod = modifier(delta)
        steps.append((d0, name, "new name" if mod == "straight" else "turn", mod))
        street = name

    out = []
    for k, (d0, name, kind, mod) in enumerate(steps):
        d1 = steps[k + 1][0] if k + 1 < len(steps) else line.length
        m = {"type": kind, "location": line.lonlat_at(d0)}
        if mod:
            m["modifier"] = mod
        out.append({"distance": round(d1 - d0, 1), "duration": round(duration_s * (d1 - d0) / line.length, 1),
                    "name": name, "maneuver": m})
    lat, lon = coords[-1]
    out.append({"distance": 0.0, "duration": 0.0, "name": "", "maneuver": {"type": "arrive", "location": [lon, lat]}})
    return out
