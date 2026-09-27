"""Wiring shared by the CLI and tests: cached network load, store, coordinator, replay clock."""
from __future__ import annotations

import hashlib
import pickle
import time

import pandas as pd

from .config import Config
from .coordinator import Coordinator
from .forecast_store import ForecastStore
from .network import RoadNetwork
from .storage import Storage


def load_network(cfg: Config, use_cache: bool = True) -> RoadNetwork:
    """Build from artifacts; cache keyed by the artifacts' sizes and mtimes (the version inside is content-hashed)."""
    nc = cfg.network
    net_dir = cfg.path(nc.sim_root) / nc.network
    files = [cfg.path(nc.segments), cfg.path(nc.patch)] + [net_dir / f for f in
             ("network.json", "crosswalk.csv", "arcs_c90.json", "patch.con.xml", "net_c90.net.xml")]
    key = hashlib.sha256("|".join(f"{f}:{f.stat().st_size}:{f.stat().st_mtime_ns}" for f in files if f.exists())
                         .encode()).hexdigest()[:16]
    cache = cfg.path(nc.cache_dir) / f"network_{nc.network}_{key}.pkl"
    if use_cache and cache.exists():
        with open(cache, "rb") as fh:
            return pickle.load(fh)
    net = RoadNetwork.from_artifacts(cfg)
    if use_cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        with open(cache, "wb") as fh:
            pickle.dump(net, fh, protocol=pickle.HIGHEST_PROTOCOL)
    return net


def replay_clock(start_epoch: float):
    """Clock that starts at start_epoch and advances with wall time (for fixtures issued in the past/future).
    Only for development; production uses time.time."""
    wall0 = time.time()
    return lambda: start_epoch + (time.time() - wall0)


def parse_now(now: str | None, store: ForecastStore):
    if now in (None, "wall"):
        return time.time
    if now == "issued":
        if store.current is None:
            return time.time
        return replay_clock(store.current.issued_at + 60.0)
    t = pd.Timestamp(now)
    t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    return replay_clock(t.timestamp())


def build(cfg: Config, db_path: str | None = None, now: str | None = "issued", selector: str | None = None,
          net: RoadNetwork | None = None) -> Coordinator:
    net = net or load_network(cfg)
    store = ForecastStore(net, cfg.forecast.bucket_min, cfg.forecast.horizons, cfg.forecast.max_issue_age_min)
    store.publish(cfg.path(cfg.forecast.path))
    storage = Storage(db_path if db_path is not None else cfg.path(cfg.ledger.db_path))
    return Coordinator(cfg, net, store, storage, clock=parse_now(now, store), selector=selector)
