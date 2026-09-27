"""Checkpoint metadata, compatibility checks and RNG state.

Layout of one checkpoint directory:
    meta.json    algo, feature/action schema, network + forecaster identity, scenario split, seed, counters, config
    policy.zip   MaskablePPO (SB3 format, includes optimizer state)      | ddqn.pt (+ replay.npz) for Double DQN
    rng.pkl      python / numpy / torch RNG states at save time
Resuming restarts the environment at an episode boundary: it is not a bit-for-bit continuation of a rollout.
"""
from __future__ import annotations

import json
import pickle
import random
import time
from pathlib import Path

import numpy as np

from ..config import Config
from ..network import sha256_file
from . import features as feat


def forecaster_identity(cfg: Config) -> dict:
    ec = cfg.env
    ident = {"mode": ec.forecast_mode}
    if ec.forecast_mode == "model":
        p = cfg.path(ec.forecast_checkpoint)
        ident.update({"checkpoint": str(p), "sha256": sha256_file(p) if p.exists() else None})
    return ident


def make_meta(cfg: Config, algo: str, seed: int, network_version: str, counters: dict, split_manifest: dict,
              extra: dict | None = None) -> dict:
    return {"algo": algo, "schema": feat.schema(cfg.rl.k), "network_version": network_version,
            "forecaster": forecaster_identity(cfg), "seed": seed, "counters": counters,
            "scenario_manifest": split_manifest, "config": cfg.to_dict(), "config_hash": cfg.hash(),
            "candidates": cfg.candidates.__dict__, "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"), **(extra or {})}


def problems(meta: dict, cfg: Config, network_version: str) -> list[str]:
    """Why a checkpoint cannot be used with this configuration (empty = compatible)."""
    out = []
    sch = meta.get("schema", {})
    want = feat.schema(cfg.rl.k)
    if sch.get("version") != want["version"]:
        out.append(f"feature schema {sch.get('version')} != {want['version']}")
    if sch.get("k") != cfg.rl.k or sch.get("dim") != want["dim"]:
        out.append(f"action/observation shape (k={sch.get('k')}, dim={sch.get('dim')}) != (k={cfg.rl.k}, dim={want['dim']})")
    if sch.get("candidate_features") != want["candidate_features"] or sch.get("global_features") != want["global_features"]:
        out.append("feature order differs")
    if meta.get("network_version") != network_version:
        out.append(f"network {meta.get('network_version')} != {network_version}")
    if meta.get("candidates", {}).get("k") != cfg.candidates.k:
        out.append("candidate K differs")
    return out


def save_meta(d: Path, meta: dict) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(json.dumps(meta, indent=1, default=str))


def load_meta(d: Path) -> dict:
    return json.loads((Path(d) / "meta.json").read_text())


def save_rng(d: Path) -> None:
    import torch
    with open(d / "rng.pkl", "wb") as f:
        pickle.dump({"python": random.getstate(), "numpy": np.random.get_state(), "torch": torch.get_rng_state()}, f)


def load_rng(d: Path) -> None:
    import torch
    p = d / "rng.pkl"
    if not p.exists():
        return
    with open(p, "rb") as f:
        s = pickle.load(f)
    random.setstate(s["python"])
    np.random.set_state(s["numpy"])
    torch.set_rng_state(s["torch"])
