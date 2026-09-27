"""Small planar geometry helpers (local equirectangular metres; fine at patch scale)."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

EARTH_R = 6371008.8


@dataclass(frozen=True)
class LocalProj:
    """lon/lat <-> local metres around (lon0, lat0). Error < 0.1% within a few km."""
    lon0: float
    lat0: float

    @property
    def kx(self) -> float:
        return math.radians(1) * EARTH_R * math.cos(math.radians(self.lat0))

    @property
    def ky(self) -> float:
        return math.radians(1) * EARTH_R

    def fwd(self, coords) -> np.ndarray:
        a = np.asarray(coords, dtype=float).reshape(-1, 2)
        return np.column_stack(((a[:, 0] - self.lon0) * self.kx, (a[:, 1] - self.lat0) * self.ky))

    def inv(self, xy) -> np.ndarray:
        a = np.asarray(xy, dtype=float).reshape(-1, 2)
        return np.column_stack((a[:, 0] / self.kx + self.lon0, a[:, 1] / self.ky + self.lat0))


def haversine_m(lon1, lat1, lon2, lat2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(min(1.0, math.sqrt(h)))


def polyline_length(xy: np.ndarray) -> float:
    if len(xy) < 2:
        return 0.0
    return float(np.hypot(*np.diff(xy, axis=0).T).sum())


def sample_polyline(xy: np.ndarray, step: float) -> tuple[np.ndarray, np.ndarray]:
    """Points every ~step metres along a polyline (incl. both ends) and the unit direction at each."""
    xy = np.asarray(xy, dtype=float)
    seg = np.diff(xy, axis=0)
    seglen = np.hypot(seg[:, 0], seg[:, 1])
    keep = seglen > 1e-9
    if not keep.any():
        return xy[:1], np.array([[1.0, 0.0]])
    seg, seglen, starts = seg[keep], seglen[keep], xy[:-1][keep]
    total = seglen.sum()
    n = max(2, int(math.ceil(total / step)) + 1)
    d = np.linspace(0, total, n)
    cum = np.concatenate(([0.0], np.cumsum(seglen)))
    idx = np.clip(np.searchsorted(cum, d, side="right") - 1, 0, len(seglen) - 1)
    t = (d - cum[idx]) / seglen[idx]
    pts = starts[idx] + seg[idx] * t[:, None]
    dirs = seg[idx] / seglen[idx][:, None]
    return pts, dirs


def midpoint(xy: np.ndarray) -> np.ndarray:
    """Point halfway along a polyline."""
    pts, _ = sample_polyline(xy, max(polyline_length(xy) / 2, 1e-6))
    return pts[len(pts) // 2]


def point_polyline_dist(pts: np.ndarray, xy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Distance from each point to a polyline, and the polyline's unit direction at the closest spot."""
    pts = np.asarray(pts, dtype=float).reshape(-1, 2)
    a, b = xy[:-1], xy[1:]
    ab = b - a
    L2 = (ab ** 2).sum(1)
    L2[L2 == 0] = 1e-12
    ap = pts[:, None, :] - a[None, :, :]
    t = np.clip((ap * ab[None]).sum(2) / L2[None], 0, 1)
    proj = a[None] + t[..., None] * ab[None]
    d = np.hypot(*(pts[:, None, :] - proj).transpose(2, 0, 1))
    j = d.argmin(1)
    dirs = ab[j] / np.sqrt(L2[j])[:, None]
    return d[np.arange(len(pts)), j], dirs


def bearing_xy(xy: np.ndarray) -> float:
    """Compass-free heading angle (radians, atan2 of end - start)."""
    v = xy[-1] - xy[0]
    return math.atan2(v[1], v[0])
