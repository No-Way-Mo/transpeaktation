"""Coordinated-routing settings (`configs/coordinated_routing_v2.yaml`).

Every number here is a starting setting from ROUTING_IMPLEMENTATION_V2.md, not a tuned optimum. Paths are relative
to ml/.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

ML_DIR = Path(__file__).resolve().parents[1]


@dataclass
class NetworkCfg:
    sim_root: str = "data/sf_citywide"
    network: str = "net_v3"                  # folder with arcs_c90.json / crosswalk.csv / network.json
    segments: str = "data/sf_citywide/batches/b3_verify/export/segments.parquet"
    patch: str = "data/sf_citywide/prepared/patch.json"
    cache_dir: str = "data/coordination/network_cache"
    max_snap_m: float = 75.0                 # coordinates farther than this from a routable road are unsupported
    snap_tie_m: float = 3.0                  # both directions of a two-way street within this of the best are tried


@dataclass
class ForecastCfg:
    path: str = "data/coordination/fixtures/forecast_fixture.parquet"   # contract-shaped export (+ .closures.parquet)
    max_issue_age_min: float = 20.0
    bucket_min: int = 10
    horizons: int = 6


@dataclass
class CandidateCfg:
    k: int = 5                               # maximum candidates per request
    max_searches: int = 12                   # Dijkstra runs per request (the search budget)
    overlap_penalty: float = 0.6             # weight multiplier added per earlier candidate that used the road
    max_overlap: float = 0.9                 # drop alternatives sharing more than this share of the fastest's time
    detour_abs_s: float = 180.0              # ETA <= fastest + min(detour_abs_s, detour_rel * fastest)
    detour_rel: float = 0.15
    min_weight_s: float = 0.01               # floor so zero-length roads keep a positive Dijkstra weight


@dataclass
class LedgerCfg:
    bin_min: int = 5
    spread: list = field(default_factory=lambda: [1.0])   # timing kernel over adjacent bins, centred; sums to 1
    provisional_ttl_s: float = 60.0
    accepted_grace_s: float = 900.0          # accepted but never started: released this long after departure
    active_grace_s: float = 1800.0           # active: released this long after the planned arrival
    db_path: str = "data/coordination/ledger.sqlite"


@dataclass
class ScoreCfg:
    lam: float = 60.0                        # seconds-equivalent selection units per unit of concentration penalty
    exposure_ref_s: float = 60.0             # w = free-flow seconds on the road / exposure_ref_s
    tie_s: float = 0.5                       # near-ties (score within this) broken by a seeded hash
    # participating-entry budget per lane per 5-min bin, by road class. Policy assumptions, NOT measured capacity.
    budget_per_lane: dict = field(default_factory=lambda: {
        "motorway": 60.0, "trunk": 45.0, "primary": 30.0, "secondary": 24.0, "tertiary": 18.0,
        "residential": 8.0, "minor": 6.0})
    default_lanes: dict = field(default_factory=lambda: {
        "motorway": 3, "trunk": 2, "primary": 2, "secondary": 2, "tertiary": 1, "residential": 1, "minor": 1})
    class_sensitivity: dict = field(default_factory=lambda: {"residential": 1.5, "minor": 1.5})


@dataclass
class BatchCfg:
    max_requests: int = 32
    max_wait_ms: float = 250.0
    solve_ms: float = 250.0
    time_scale: int = 10                     # CP-SAT integer units per second of objective
    load_scale: int = 4                      # CP-SAT integer units per participating entry
    workers: int = 1                         # 1 = deterministic


@dataclass
class ServiceCfg:
    host: str = "127.0.0.1"
    port: int = 8100
    selector: str = "heuristic"
    # per-request `selector` overrides a client may ask for; anything else is refused (400)
    allowed_selectors: list = field(default_factory=lambda: ["forecast_only", "heuristic", "batch"])
    max_body_bytes: int = 65536
    sweep_s: float = 30.0                    # expiry sweep period, runs even with no incoming requests


@dataclass
class ReplayCfg:
    """Replay input mode (coordination/replay.py): forecasts come from the forecast service, fed with one recorded
    synthetic run under a replay clock. Labeled everywhere; never presented as live traffic."""
    run: str = ""                            # run export parquet (time, road_segment_id, speed_mph, observed, closed)
    context: str = ""                        # context.json of that run (python -m coordination replay-context)
    forecast_url: str = "http://127.0.0.1:8200"   # token: FORECAST_API_TOKEN (env)
    state_dir: str = "data/coordination/replay_state"   # session.json + one ledger per session
    start_offset_min: int = 0                # replay starts this long after the first issue time with full history
    retry_s: float = 30.0
    timeout_s: float = 180.0


@dataclass
class LiveCfg:
    """Live input mode (coordination/live.py): the congestion map the forecaster writes to Tiger/Mongo, refreshed on
    demand by customer requests. DB URLs: TIGER_DATABASE_URL, MONGODB_URI; forecaster token: FORECAST_API_TOKEN."""
    forecast_url: str = "http://127.0.0.1:8200"
    state_dir: str = "data/coordination/live_state"   # ledger_live.sqlite
    check_s: float = 60.0                    # once the map is a bucket old, ask for a newer one at most this often
    retry_s: float = 30.0                    # with no map at all, retry this often
    wait_s: float = 150.0                    # a request with no usable map waits at most this long for one
    timeout_s: float = 180.0


@dataclass
class EnvCfg:
    """Interactive SUMO episode (coordination/rl/sumo_env.py). Starting settings, not tuned."""
    sim_root: str = "data/sf_citywide"
    batch: str = "b3_verify"                  # quality-gate-passed, same net_v3 as the forecaster
    splits: str = "data/forecast/datasets/b3_verify_v3net_ep1/splits.json"   # reuse the forecaster's event groups
    history_s: int = 3600                     # 6 completed 10-min buckets before the first scored decision
    decision_window_s: int = 1800
    max_drain_s: int = 1800                   # after the window: until in-scope vehicles arrive, at most this
    participation: float = 0.05               # share of eligible trips departing in the window
    max_participants: int = 150
    compliance: float = 1.0                   # first controlled setting, not a deployment assumption
    sim_seed_offsets: list = field(default_factory=lambda: [0, 1])
    forecast_mode: str = "model"              # model | fixture_debug | persistence_debug (debug modes are labeled)
    forecast_checkpoint: str = "data/forecast/experiments/event_patch_v1/best.pt"
    forecast_device: str = ""                 # "" = the forecaster's own choice (cuda if available)
    progress_every_s: int = 60
    reward_scale_s: float = 360_000.0         # fixed: reward = -(vehicle-seconds) / reward_scale_s (100 veh-h)
    out_dir: str = "data/coordination/rl/episodes"
    warm_state_cache: bool = True             # reuse a verified SUMO state at the end of the history period
    step_s: int = 1                           # TraCI step and measurement sampling period
    time_to_teleport_s: int = 300             # SUMO --time-to-teleport (teleports are counted and reported)
    sumo_backend: str = "traci"               # traci | libsumo (same simulation, in-process; TP_SUMO_BACKEND overrides)
    keep_outputs: bool = False                # also write vehroutes.xml.gz + 5-min edgedata.xml.gz per episode


@dataclass
class RLCfg:
    k: int = 5                                # action slots; must equal candidates.k (schema-versioned)
    checkpoint: str = ""                      # used by the rl selector; "" = unavailable
    device: str = "cpu"
    # MaskablePPO
    ppo_lr: float = 3e-4
    n_steps: int = 1024
    batch_size: int = 128
    n_epochs: int = 5
    clip_range: float = 0.2
    ent_coef: float = 0.01
    gamma: float = 1.0                        # finite request-indexed episodes: no request-density discounting
    gae_lambda: float = 1.0
    net_arch: list = field(default_factory=lambda: [128, 128])
    n_envs: int = 1
    # masked Double DQN
    dqn_lr: float = 1e-4
    buffer_size: int = 50_000
    dqn_batch_size: int = 64
    learning_starts: int = 500
    target_update: int = 1000
    eps_start: float = 1.0
    eps_end: float = 0.05
    eps_decay_decisions: int = 10_000
    train_freq: int = 1
    grad_clip: float = 10.0
    # budget (a pilot; reaching it does not mean convergence)
    max_decisions: int = 50_000
    wall_hours: float = 2.0
    eval_every_decisions: int = 5000
    eval_episodes: int = 1
    save_every_decisions: int = 1000
    run_dir: str = "data/coordination/rl/runs"


@dataclass
class BenchmarkCfg:
    """Matched selector comparison (coordination/benchmark). Every policy replays the same scenarios, simulation
    seeds, participants, compliance draws and warm start; only the route choices (and so the traffic) differ."""
    policies: list = field(default_factory=lambda: ["forecast_only", "heuristic", "batch", "rl_ppo", "rl_ddqn"])
    checkpoints: dict = field(default_factory=lambda: {"rl_ppo": "data/coordination/rl/runs/ppo_s0/best",
                                                       "rl_ddqn": "data/coordination/rl/runs/ddqn_s0/best"})
    screening_split: str = "val"             # development scenarios (tuning allowed)
    screening_scenarios: int = 3
    heldout_split: str = "test"              # frozen evaluation (no tuning after looking)
    heldout_scenarios: int = 6
    seeds: list = field(default_factory=lambda: [0, 1])   # simulation seed offsets (not training seeds)
    event_runs_only: bool = True             # scenarios with the event restrictions active
    batch_window_s: float = 60.0             # batch policy: requests arriving within this are decided jointly;
                                             # the wait delays their departure and is counted as vehicle time
    static_chunk: int = 32                   # static suite: requests per selector call
    workers: int = 0                         # 0 = one process per task (bounded by CPU count)
    out_dir: str = "data/coordination/benchmark"


@dataclass
class Config:
    name: str = "coordinated_routing_v2"
    network: NetworkCfg = field(default_factory=NetworkCfg)
    forecast: ForecastCfg = field(default_factory=ForecastCfg)
    candidates: CandidateCfg = field(default_factory=CandidateCfg)
    ledger: LedgerCfg = field(default_factory=LedgerCfg)
    score: ScoreCfg = field(default_factory=ScoreCfg)
    batch: BatchCfg = field(default_factory=BatchCfg)
    service: ServiceCfg = field(default_factory=ServiceCfg)
    replay: ReplayCfg = field(default_factory=ReplayCfg)
    live: LiveCfg = field(default_factory=LiveCfg)
    env: EnvCfg = field(default_factory=EnvCfg)
    rl: RLCfg = field(default_factory=RLCfg)
    benchmark: BenchmarkCfg = field(default_factory=BenchmarkCfg)
    seed: int = 0
    run_root: str = "data/coordination/runs"

    def path(self, p: str) -> Path:
        q = Path(p)
        return q if q.is_absolute() else ML_DIR / q

    def to_dict(self) -> dict:
        return asdict(self)

    def hash(self) -> str:
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True).encode()).hexdigest()[:12]


_SECTIONS = {"network": NetworkCfg, "forecast": ForecastCfg, "candidates": CandidateCfg, "ledger": LedgerCfg,
             "score": ScoreCfg, "batch": BatchCfg, "service": ServiceCfg, "replay": ReplayCfg, "live": LiveCfg, "env": EnvCfg,
             "rl": RLCfg,
             "benchmark": BenchmarkCfg}


def from_dict(d: dict) -> Config:
    d = copy.deepcopy(d or {})
    kw = {}
    for k, v in d.items():
        if k in _SECTIONS:
            cls = _SECTIONS[k]
            unknown = set(v or {}) - set(cls.__dataclass_fields__)
            if unknown:
                raise ValueError(f"unknown {k} settings: {sorted(unknown)}")
            kw[k] = cls(**(v or {}))
        elif k in ("name", "seed", "run_root"):
            kw[k] = v
        else:
            raise ValueError(f"unknown config section {k!r}")
    return Config(**kw)


def load(path: str | None) -> Config:
    if not path:
        return Config()
    p = Path(path)
    if not p.is_absolute() and not p.exists():
        p = ML_DIR / p
    return from_dict(yaml.safe_load(p.read_text()) or {})
