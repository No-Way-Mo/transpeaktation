"""Experiment settings. One YAML file per experiment (`configs/*.yaml`); `inherit:` pulls in a base file.

Paths in the YAML are relative to ml/. Every stage writes under `data/forecast/` (gitignored) except readable
reports in `reports/`.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ML_DIR = Path(__file__).resolve().parents[1]
SF_TZ = ZoneInfo("America/Los_Angeles")
MPH_PER_MPS = 2.2369362920544
SPEED_FLOOR_MPS = 0.1   # same floor as eventsim.citywide_batch.export: travel_time_s = length / max(speed, 0.1)


@dataclass
class DataCfg:
    sim_root: str = "data/sf_citywide"
    batch: str = "b3_verify"
    network: str = "net_v3"                   # network folder the batch was simulated on
    dataset_id: str = "b3_verify_v3net_ep1"
    out_root: str = "data/forecast"
    bucket_min: int = 10
    history_steps: int = 6
    horizon_steps: int = 6
    max_ffill: int = 2
    phases: list = field(default_factory=lambda: ["demand"])   # every window bucket must be in one of these
    excluded_batches: list = field(default_factory=lambda: ["calib_v3"])
    split_salt: str = "event_patch_v1"
    n_val_groups: int = 1
    n_test_groups: int = 1
    fixed_split: dict | None = None           # {"val": [...], "test": [...]} event groups; overrides the hash order
    extra_datasets: list | None = None        # [{batch, dataset_id}]: more frozen datasets (same network / roads)


@dataclass
class GraphCfg:
    patch_size: int = 128


@dataclass
class EventCfg:
    context_radius_m: float = 3000.0         # (event, road) pairs beyond this carry no context
    distance_scales_m: list = field(default_factory=lambda: [300.0, 1000.0, 3000.0])
    max_hops: int = 8
    clip_hours: float = 6.0
    near_radius_m: float = 1000.0            # evaluation stratum "event-near"


@dataclass
class ModelCfg:
    hidden: int = 64
    heads: int = 4
    blocks: int = 3
    dropout: float = 0.1
    use_events: bool = True
    event_hops: int = 2                      # sparse up/downstream propagation steps of the context
    # optional extensions (EVENT_ANTICIPATION_IMPROVEMENTS_PLAN.md); None = absent, keeps old config hashes
    jam_head: bool | None = None             # P(jam) logit per road x horizon from the decoder state
    quantiles: list | None = None            # e.g. [0.1, 0.9]: z quantile heads (offsets around the point forecast)
    onset_features: bool | None = None       # per-case recent traffic near the footprint (history, causal)
    route_features: bool | None = None       # per-(case, road) shortest-path load toward / away from the footprint
    event_attn_pool: bool | None = None      # learned attention pooling over each road's event pairs (+ mean/max)
    oracle_features: bool | None = None      # DIAGNOSTIC ONLY: hidden per-run event parameters (not deployable)


MODEL_EXTENSIONS = ("jam_head", "quantiles", "onset_features", "route_features", "event_attn_pool", "oracle_features")


@dataclass
class TrainCfg:
    seed: int = 0
    lr: float = 1e-3
    weight_decay: float = 1e-4
    grad_clip: float = 1.0
    max_epochs: int = 40
    patience: int = 8
    amp: bool = True
    device: str = "auto"
    origins_per_family: int = 24             # balanced sampling: windows drawn per training family per epoch
    huber_delta: float = 1.0
    congestion_loss_weight: float = 0.0      # optional; off for the first experiment


@dataclass
class EvalCfg:
    buildup_congestion: float = 0.5          # declared before evaluation (see reports)
    buildup_prior_max: float = 0.3
    headline_horizons: list = field(default_factory=lambda: [10, 30, 60])


@dataclass
class Config:
    name: str = "event_patch_v1"
    data: DataCfg = field(default_factory=DataCfg)
    graph: GraphCfg = field(default_factory=GraphCfg)
    events: EventCfg = field(default_factory=EventCfg)
    model: ModelCfg = field(default_factory=ModelCfg)
    train: TrainCfg = field(default_factory=TrainCfg)
    eval: EvalCfg = field(default_factory=EvalCfg)
    source_path: str = ""

    # -------------------------------------------------------------- paths
    def path(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else ML_DIR / p

    @property
    def sim_root(self) -> Path:
        return self.path(self.data.sim_root)

    @property
    def batch_dir(self) -> Path:
        return self.sim_root / "batches" / self.data.batch

    @property
    def net_dir(self) -> Path:
        return self.sim_root / self.data.network

    @property
    def dataset_dir(self) -> Path:
        return self.path(self.data.out_root) / "datasets" / self.data.dataset_id

    @property
    def exp_dir(self) -> Path:
        return self.path(self.data.out_root) / "experiments" / self.name

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("source_path")
        for k in ("fixed_split", "extra_datasets"):   # absent = old behaviour; keeps earlier config hashes
            if d["data"].get(k) is None:
                d["data"].pop(k, None)
        for k in MODEL_EXTENSIONS:
            if d["model"].get(k) is None:
                d["model"].pop(k, None)
        return d

    def hash(self) -> str:
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True).encode()).hexdigest()[:16]


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def from_dict(d: dict) -> Config:
    sections = {"data": DataCfg, "graph": GraphCfg, "events": EventCfg, "model": ModelCfg, "train": TrainCfg,
                "eval": EvalCfg}
    unknown = set(d) - set(sections) - {"name"}
    if unknown:
        raise ValueError(f"unknown config sections: {sorted(unknown)}")
    kw = {"name": d.get("name", "event_patch_v1")}
    for k, cls in sections.items():
        sub = d.get(k, {}) or {}
        bad = set(sub) - set(cls.__dataclass_fields__)
        if bad:
            raise ValueError(f"unknown keys in {k}: {sorted(bad)}")
        kw[k] = cls(**sub)
    return Config(**kw)


def _load_raw(path: Path, depth: int = 0) -> dict:
    """YAML with `inherit:` resolved recursively (base first, child overrides)."""
    if depth > 16:
        raise ValueError(f"inherit chain too deep at {path}")
    raw = yaml.safe_load(path.read_text()) or {}
    if "inherit" in raw:
        raw = _merge(_load_raw(path.parent / raw.pop("inherit"), depth + 1), raw)
    return raw


def load(path: str | Path) -> Config:
    path = Path(path)
    if not path.is_absolute() and not path.exists():
        path = ML_DIR / path
    raw = _load_raw(path)
    retrain = raw.pop("retrain", None)   # transfer-training settings (forecast/retrain.py); not part of the hash
    cfg = from_dict(raw)
    cfg.source_path = str(path)
    cfg.retrain = retrain
    return cfg


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, default=str))
    tmp.replace(path)


def read_json(path: Path):
    return json.loads(Path(path).read_text())
