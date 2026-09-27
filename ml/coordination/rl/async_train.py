"""Asynchronous actor-learner training for the route-choice environment (masked PPO and masked Double DQN).

Why: SB3's vectorised environments step in lock-step, so every step waits for the slowest of N SUMO episodes
(resets ~25 s, end-of-episode drains 1-3 min). Here each actor process plays whole episodes on its own and never
waits for another; the learner trains on whatever arrives and publishes new weights, which actors load at the start
of their next episode.

* Actors: one SUMO environment each (torch single-threaded), current policy weights, full episodes -> queue.
  PPO actors sample from the masked policy and record log-prob; DDQN actors act epsilon-greedy with the learner's
  published epsilon. Masks are respected everywhere; an actor never applies a masked action.
* Learner (this process):
  - `appo` (masked actor-critic PPO): collects >= rollout decisions from episodes whose policy is at most
    `max_staleness` versions old, advantages G_t - V_current(s_t) with gamma = 1 over the finite episode (as in
    RL_ROUTING_RESEARCH_AND_PLAN.md §4), clipped importance-weighted surrogate with the recorded behaviour log-probs,
    value loss, masked entropy bonus. Older episodes are dropped and counted.
  - `ddqn`: every transition goes into the existing MaskedDDQN replay; one gradient update per `train_freq`
    transitions after `learning_starts`; target sync as configured.
* Validator process: repeatedly evaluates the latest weights greedily on the validation scenarios and sends the
  evaluated weights with the result, so `best/` is exactly the policy that scored best.
* Budget: `rl.max_decisions` or `rl.wall_hours`; `latest/` is saved every `save_every_decisions` and at the end.
Checkpoints use the existing meta.json (schema, network, forecaster, scenario manifest) and load through
`rl/policy.py` (`appo.pt` / `ddqn.pt`).
"""
from __future__ import annotations

import json
import os
import queue
import time
from functools import partial
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

from . import checkpoint as ck
from . import features as feat

NEG = -1e9


class ActorCritic(nn.Module):
    def __init__(self, obs_dim: int, k: int, hidden=(128, 128)):
        super().__init__()
        def mlp(out):
            layers, d = [], obs_dim
            for h in hidden:
                layers += [nn.Linear(d, h), nn.Tanh()]
                d = h
            return nn.Sequential(*layers, nn.Linear(d, out))
        self.pi, self.v = mlp(k), mlp(1)
        self.obs_dim, self.k, self.hidden = obs_dim, k, tuple(hidden)

    def forward(self, x):
        return self.pi(x), self.v(x).squeeze(-1)


def masked_dist(logits: torch.Tensor, mask: torch.Tensor):
    return torch.distributions.Categorical(logits=torch.where(mask, logits, torch.full_like(logits, NEG)))


# ---------------------------------------------------------------- weight exchange (atomic files)

def publish(rd: Path, payload: dict) -> None:
    tmp = rd / f"live.{os.getpid()}.tmp"
    torch.save(payload, tmp)
    os.replace(tmp, rd / "live.pt")


def read_live(rd: Path, have: int):
    p = rd / "live.pt"
    for _ in range(3):
        try:
            d = torch.load(p, map_location="cpu", weights_only=False)
            return d if d["version"] > have else None
        except (FileNotFoundError, EOFError, RuntimeError):
            time.sleep(0.2)
    return None


def build_net(algo: str, obs_dim: int, k: int, hidden):
    if algo == "appo":
        return ActorCritic(obs_dim, k, hidden)
    from .ddqn import QNet
    return QNet(obs_dim, k, hidden)


# ---------------------------------------------------------------- environment factory (picklable by reference)

_NET: dict = {}


def make_route_env(cfg_dict: dict, split: str, seed: int, tag: str, allow_debug: bool = False):
    from ..config import from_dict
    from ..runtime import load_network
    from . import scenario
    from .sumo_env import RouteChoiceEnv
    cfg = from_dict(cfg_dict)
    if "net" not in _NET:
        _NET["net"] = load_network(cfg)
    specs = scenario.load(cfg, split)
    return RouteChoiceEnv(cfg, _NET["net"], specs, policy_name=tag, allow_debug_forecast=allow_debug, seed=seed, tag=tag)


# ---------------------------------------------------------------- actor / validator processes

def actor_main(factory_blob: bytes, algo: str, rd: str, seed: int, out_q, stop, actor_id: int, obs_dim: int, k: int,
               hidden) -> None:
    import cloudpickle
    torch.set_num_threads(1)
    rd = Path(rd)
    env = cloudpickle.loads(factory_blob)(seed)
    rng = np.random.default_rng(seed)
    net = build_net(algo, obs_dim, k, hidden)
    version, eps = -1, 1.0
    try:
        while not stop.is_set():
            live = read_live(rd, version)
            if live is not None:
                net.load_state_dict(live["state"])
                version, eps = live["version"], live.get("epsilon", 0.0)
            obs, info = env.reset()
            if info.get("empty_episode"):
                continue
            ep = {k_: [] for k_ in ("obs", "act", "rew", "logp", "mask", "next_mask")}
            done, term, trunc = False, False, False
            while not done and not stop.is_set():
                mask = np.asarray(env.action_masks(), bool)
                with torch.no_grad():
                    x = torch.as_tensor(obs, dtype=torch.float32)[None]
                    m = torch.as_tensor(mask)[None]
                    if algo == "appo":
                        logits, _ = net(x)
                        dist = masked_dist(logits, m)
                        a = int(dist.sample()[0])
                        lp = float(dist.log_prob(torch.tensor([a]))[0])
                    else:
                        if rng.random() < eps:
                            a = int(rng.choice(np.flatnonzero(mask)))
                        else:
                            a = int(torch.where(m, net(x), torch.full((1, k), NEG)).argmax(-1)[0])
                        lp = 0.0
                if not mask[a]:
                    raise RuntimeError("actor chose a masked slot")
                nobs, r, term, trunc, info = env.step(a)
                for key, v in (("obs", obs), ("act", a), ("rew", r), ("logp", lp), ("mask", mask),
                               ("next_mask", np.asarray(info["action_mask"], bool))):
                    ep[key].append(v)
                obs, done = nobs, term or trunc
            if not done:
                break                                      # stopped mid-episode: the partial episode is dropped
            out_q.put({"kind": "episode", "actor": actor_id, "version": version, "terminated": bool(term),
                       "truncated": bool(trunc), "summary": info.get("episode_summary"),
                       **{key: np.asarray(v) for key, v in ep.items()}})
    finally:
        env.close()


def validator_main(factory_blob: bytes, algo: str, rd: str, seed: int, out_q, stop, episodes: int, obs_dim: int,
                   k: int, hidden, every_s: float) -> None:
    import cloudpickle
    torch.set_num_threads(1)
    rd = Path(rd)
    env = cloudpickle.loads(factory_blob)(seed)
    net = build_net(algo, obs_dim, k, hidden)
    version = -1
    try:
        while not stop.is_set():
            live = read_live(rd, version)
            if live is None:
                stop.wait(every_s)
                continue
            net.load_state_dict(live["state"])
            version = live["version"]
            rets, summaries = [], []
            for e in range(episodes):
                specs = getattr(env, "specs", None)
                obs, info = env.reset(options={"scenario": specs[e % len(specs)].scenario_id, "seed_offset": 0}
                                      if specs else None)
                ret, done = 0.0, bool(info.get("empty_episode"))
                while not done and not stop.is_set():
                    mask = torch.as_tensor(np.asarray(env.action_masks(), bool))[None]
                    with torch.no_grad():
                        x = torch.as_tensor(obs, dtype=torch.float32)[None]
                        out = net(x)[0] if algo == "appo" else net(x)
                        a = int(torch.where(mask, out, torch.full_like(out, NEG)).argmax(-1)[0])
                    obs, r, term, trunc, info = env.step(a)
                    ret += r
                    done = term or trunc
                if stop.is_set():
                    return
                rets.append(ret)
                summaries.append(info.get("episode_summary"))
            out_q.put({"kind": "validation", "version": version, "returns": rets, "mean_return": float(np.mean(rets)),
                       "state": {k_: v.clone() for k_, v in net.state_dict().items()}, "summaries": summaries})
    finally:
        env.close()


# ---------------------------------------------------------------- learner

class _Log:
    def __init__(self, d: Path):
        d.mkdir(parents=True, exist_ok=True)
        self.f = open(d / "log.jsonl", "a", encoding="utf-8")

    def __call__(self, **kw):
        kw["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.f.write(json.dumps(kw, default=str) + "\n")
        self.f.flush()
        print(json.dumps({k: v for k, v in kw.items() if k not in ("summary", "summaries")}, default=str)[:400],
              flush=True)


def _save(d: Path, algo: str, state: dict, obs_dim: int, k: int, hidden, cfg, seed, network_version, counters,
          manifest, extra=None, opt_state=None) -> None:
    d.mkdir(parents=True, exist_ok=True)
    if algo == "appo":
        torch.save({"net": state, "obs_dim": obs_dim, "k": k, "hidden": list(hidden), "opt": opt_state},
                   d / "appo.pt")
    else:
        torch.save({"q": state, "q_target": state, "obs_dim": obs_dim, "k": k, "hidden": list(hidden)}, d / "ddqn.pt")
    ck.save_meta(d, ck.make_meta(cfg, algo, seed, network_version, dict(counters), manifest,
                                 {"trainer": "async_actor_learner", **(extra or {})}))


def train_async(cfg, algo: str, seed: int, env_factory, val_factory, network_version: str, manifest: dict,
                name: str | None = None, n_actors: int | None = None, rollout: int = 8192, max_staleness: int = 4,
                log=None) -> dict:
    """algo: 'appo' | 'ddqn'. env_factory(seed) / val_factory(seed) -> env; must be picklable with cloudpickle."""
    import multiprocessing as mp
    import cloudpickle
    from .ddqn import MaskedDDQN
    from .train import run_dir

    rl = cfg.rl
    rd = run_dir(cfg, algo, seed, name or f"{algo}_async_s{seed}")
    rd.mkdir(parents=True, exist_ok=True)
    lg = _Log(rd)
    obs_dim, k, hidden = feat.obs_dim(rl.k), rl.k, tuple(rl.net_arch)
    n_actors = n_actors or rl.n_envs
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    if algo == "appo":
        net = ActorCritic(obs_dim, k, hidden)
        opt = torch.optim.Adam(net.parameters(), lr=rl.ppo_lr)
        agent = None
    else:
        agent = MaskedDDQN(obs_dim, k, rl, seed)
        net, opt = agent.q, agent.opt
    p0 = torch.cat([p.detach().flatten() for p in net.parameters()]).clone()
    version = 0
    counters = {"decisions": 0, "episodes": 0, "updates": 0, "dropped_stale_episodes": 0, "wall_s": 0.0,
                "best_val_return": None, "best_version": None, "actors": n_actors}

    def eps():
        return agent.epsilon() if agent is not None else 0.0

    publish(rd, {"version": version, "state": net.state_dict(), "epsilon": eps()})
    ctx = mp.get_context("spawn")
    out_q, stop = ctx.Queue(maxsize=4 * n_actors + 8), ctx.Event()
    blob = cloudpickle.dumps(env_factory)
    procs = [ctx.Process(target=actor_main, args=(blob, algo, str(rd), seed + 1000 * (i + 1), out_q, stop, i,
                                                  obs_dim, k, hidden), daemon=True) for i in range(n_actors)]
    if val_factory is not None:
        procs.append(ctx.Process(target=validator_main, args=(cloudpickle.dumps(val_factory), algo, str(rd),
                                                              seed + 7919, out_q, stop, rl.eval_episodes, obs_dim,
                                                              k, hidden, 30.0), daemon=True))
    for p in procs:
        p.start()
    lg(event="start", algo=algo, actors=n_actors, rollout=rollout, max_staleness=max_staleness,
       validator=val_factory is not None)
    t0 = time.time()
    buf, buf_n = [], 0
    next_save = rl.save_every_decisions
    stopped_by = None
    last_pub = time.time()
    try:
        while stopped_by is None:
            try:
                msg = out_q.get(timeout=5)
            except queue.Empty:
                msg = None
                if not any(p.is_alive() for p in procs[:n_actors]):
                    stopped_by = "actors_died"
            if msg is not None and msg["kind"] == "validation":
                better = counters["best_val_return"] is None or msg["mean_return"] > counters["best_val_return"]
                lg(event="validation", version=msg["version"], mean_return=msg["mean_return"], returns=msg["returns"],
                   decisions=counters["decisions"], best=better, summaries=msg["summaries"])
                if better:
                    counters["best_val_return"], counters["best_version"] = msg["mean_return"], msg["version"]
                    _save(rd / "best", algo, msg["state"], obs_dim, k, hidden, cfg, seed, network_version, counters,
                          manifest, {"validation": {"mean_return": msg["mean_return"], "returns": msg["returns"],
                                                    "version": msg["version"]}})
            elif msg is not None:
                n = len(msg["act"])
                counters["decisions"] += n
                counters["episodes"] += 1
                s = msg.get("summary") or {}
                lg(event="episode", decisions=counters["decisions"], version=msg["version"], actor=msg["actor"],
                   steps=n, ret=float(msg["rew"].sum()), vehicle_hours=s.get("in_scope_vehicle_hours"),
                   scenario=s.get("scenario"), epsilon=eps() if agent is not None else None, summary=s)
                if agent is not None:                          # ---- DDQN: replay + updates
                    obs = msg["obs"]
                    nxt = np.concatenate([obs[1:], np.zeros_like(obs[:1])])
                    for i in range(n):
                        last = i == n - 1
                        agent.replay.add(obs[i], int(msg["act"][i]), float(msg["rew"][i]), nxt[i],
                                         last and msg["terminated"], last and msg["truncated"], msg["next_mask"][i])
                        agent.decisions += 1
                        if agent.decisions >= rl.learning_starts and agent.decisions % rl.train_freq == 0 \
                                and agent.replay.n >= rl.dqn_batch_size:
                            agent.update()
                    counters["updates"] = agent.updates
                    if time.time() - last_pub > 10:
                        version += 1
                        publish(rd, {"version": version, "state": net.state_dict(), "epsilon": eps()})
                        last_pub = time.time()
                else:                                          # ---- PPO: on-policy-ish rollout buffer
                    if msg["version"] < version - max_staleness:
                        counters["dropped_stale_episodes"] += 1
                    else:
                        buf.append(msg)
                        buf_n += n
                    if buf_n >= rollout:
                        stats = _ppo_update(net, opt, buf, rl, rng)
                        version += 1
                        counters["updates"] += 1
                        publish(rd, {"version": version, "state": net.state_dict()})
                        lg(event="update", version=version, decisions=counters["decisions"], samples=buf_n, **stats)
                        buf, buf_n = [], 0
            if counters["decisions"] >= next_save:
                next_save += rl.save_every_decisions
                _save(rd / "latest", algo, net.state_dict(), obs_dim, k, hidden, cfg, seed, network_version, counters,
                      manifest, opt_state=opt.state_dict())
            counters["wall_s"] = time.time() - t0
            if counters["decisions"] >= rl.max_decisions:
                stopped_by = "max_decisions"
            elif counters["wall_s"] / 3600 >= rl.wall_hours:
                stopped_by = "wall_hours"
    finally:
        stop.set()
        _save(rd / "latest", algo, net.state_dict(), obs_dim, k, hidden, cfg, seed, network_version, counters, manifest,
              opt_state=opt.state_dict())
        deadline = time.time() + 90
        while time.time() < deadline and any(p.is_alive() for p in procs):
            try:
                out_q.get(timeout=1)                           # drain so actors blocked on put() can exit
            except queue.Empty:
                pass
        for p in procs:
            if p.is_alive():
                p.terminate()
    change = float(torch.linalg.vector_norm(torch.cat([p.detach().flatten() for p in net.parameters()]) - p0))
    summ = {"algo": algo, "seed": seed, **counters, "stopped_by": stopped_by, "param_change_l2": change,
            "decisions_per_s": round(counters["decisions"] / max(counters["wall_s"], 1e-9), 2), "run_dir": str(rd),
            "note": "asynchronous actor-learner; a budgeted run is not convergence"}
    (rd / "summary.json").write_text(json.dumps(summ, indent=1, default=str))
    lg(event="done", **summ)
    lg.f.close()
    return summ


def _returns(rew: np.ndarray, gamma: float) -> np.ndarray:
    out, g = np.zeros(len(rew), np.float64), 0.0
    for i in range(len(rew) - 1, -1, -1):
        g = rew[i] + gamma * g
        out[i] = g
    return out


def _ppo_update(net: ActorCritic, opt, episodes: list, rl, rng) -> dict:
    """Clipped PPO on complete episodes; advantages from rl.gamma returns-to-go minus the CURRENT value estimate
    (behaviour log-probs recorded by the actors give the importance ratio for mildly stale episodes)."""
    obs = torch.as_tensor(np.concatenate([e["obs"] for e in episodes]), dtype=torch.float32)
    act = torch.as_tensor(np.concatenate([e["act"] for e in episodes]), dtype=torch.int64)
    mask = torch.as_tensor(np.concatenate([e["mask"] for e in episodes]), dtype=torch.bool)
    old_lp = torch.as_tensor(np.concatenate([e["logp"] for e in episodes]), dtype=torch.float32)
    ret = torch.as_tensor(np.concatenate([_returns(e["rew"], rl.gamma) for e in episodes]).astype(np.float32))
    with torch.no_grad():
        adv = ret - net(obs)[1]
    adv = (adv - adv.mean()) / (adv.std() + 1e-8)
    n = len(act)
    stats = {"pi_loss": 0.0, "v_loss": 0.0, "entropy": 0.0, "clip_frac": 0.0, "approx_kl": 0.0}
    steps = 0
    for _ in range(rl.n_epochs):
        perm = torch.as_tensor(rng.permutation(n))
        for i in range(0, n, rl.batch_size):
            b = perm[i:i + rl.batch_size]
            logits, v = net(obs[b])
            dist = masked_dist(logits, mask[b])
            lp = dist.log_prob(act[b])
            ratio = torch.exp(lp - old_lp[b])
            s1, s2 = ratio * adv[b], ratio.clamp(1 - rl.clip_range, 1 + rl.clip_range) * adv[b]
            pi_loss = -torch.min(s1, s2).mean()
            v_loss = ((v - ret[b]) ** 2).mean()
            ent = dist.entropy().mean()
            loss = pi_loss + 0.5 * v_loss - rl.ent_coef * ent
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(net.parameters(), 0.5)
            opt.step()
            with torch.no_grad():
                stats["pi_loss"] += float(pi_loss); stats["v_loss"] += float(v_loss); stats["entropy"] += float(ent)
                stats["clip_frac"] += float(((ratio - 1).abs() > rl.clip_range).float().mean())
                stats["approx_kl"] += float((old_lp[b] - lp).mean())
            steps += 1
    return {k: round(v / max(steps, 1), 6) for k, v in stats.items()}


def route_env_factories(cfg, debug_forecast: bool = False):
    """Picklable train/validation factories for the real SUMO environment."""
    d = cfg.to_dict()
    return (partial(_factory_call, d, "train", "train_async", debug_forecast),
            partial(_factory_call, d, "val", "val_async", debug_forecast))


def _factory_call(cfg_dict, split, tag, debug, seed):
    return make_route_env(cfg_dict, split, seed, tag, debug)
