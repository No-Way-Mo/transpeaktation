"""Bounded, resumable training of MaskablePPO (sb3-contrib) and masked Double DQN on RouteChoiceEnv.

Budget: stops at `rl.max_decisions` or `rl.wall_hours`, whichever first, always leaving a usable `latest/`
checkpoint and a summary with the actual decisions, episodes and wall time. Reaching the budget is not
convergence. Validation episodes (separate val-split scenarios, deterministic masked actions) select `best/`.
Resume restarts the environment at an episode boundary.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from ..config import Config
from . import checkpoint as ck
from . import features as feat
from .evaluate import run_episodes


def run_dir(cfg: Config, algo: str, seed: int, name: str | None = None) -> Path:
    return cfg.path(cfg.rl.run_dir) / (name or f"{algo}_s{seed}")


class Log:
    def __init__(self, d: Path):
        d.mkdir(parents=True, exist_ok=True)
        self.f = open(d / "log.jsonl", "a", encoding="utf-8")

    def __call__(self, **kw):
        kw["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.f.write(json.dumps(kw, default=str) + "\n")
        self.f.flush()
        msg = {k: v for k, v in kw.items() if k not in ("summary",)}
        print(json.dumps(msg, default=str), flush=True)

    def close(self):
        self.f.close()


def _param_vector(params) -> np.ndarray:
    return np.concatenate([p.detach().cpu().numpy().ravel() for p in params])


def _summaries(infos) -> list[dict]:
    return [i["episode_summary"] for i in infos if isinstance(i, dict) and "episode_summary" in i]


def train_ppo(cfg: Config, seed: int, env_factory, eval_factory, network_version: str, manifest: dict,
              resume: bool = False, name: str | None = None) -> dict:
    from sb3_contrib import MaskablePPO
    from sb3_contrib.common.maskable.evaluation import evaluate_policy
    from stable_baselines3.common.callbacks import BaseCallback
    from stable_baselines3.common.vec_env import DummyVecEnv, SubprocVecEnv

    rl = cfg.rl
    rd = run_dir(cfg, "ppo", seed, name)
    log = Log(rd)
    fns = [lambda i=i: env_factory(seed + 1000 * i) for i in range(rl.n_envs)]

    class MaskableSubprocVecEnv(SubprocVecEnv):
        """sb3-contrib detects masking with get_attr("action_masks"), which would pickle a bound method of the
        whole environment (it holds locks). Answer that probe here; masks themselves still come from env_method."""
        def get_attr(self, attr_name, indices=None):
            if attr_name == "action_masks":
                return [None] * len(self._get_indices(indices))
            return super().get_attr(attr_name, indices)

    venv = DummyVecEnv(fns) if rl.n_envs == 1 else MaskableSubprocVecEnv(fns, start_method="spawn")
    counters = {"decisions": 0, "episodes": 0, "wall_s": 0.0, "best_val_return": None}
    if resume and (rd / "latest" / "policy.zip").exists():
        meta = ck.load_meta(rd / "latest")
        probs = ck.problems(meta, cfg, network_version)
        if probs:
            raise SystemExit("cannot resume: " + "; ".join(probs))
        model = MaskablePPO.load(str(rd / "latest" / "policy.zip"), env=venv, device=rl.device)
        ck.load_rng(rd / "latest")
        counters.update(meta["counters"])
        log(event="resumed", from_decisions=counters["decisions"], note="episode-boundary restart, not bit-for-bit")
    else:
        model = MaskablePPO("MlpPolicy", venv, learning_rate=rl.ppo_lr, n_steps=rl.n_steps, batch_size=rl.batch_size,
                            n_epochs=rl.n_epochs, clip_range=rl.clip_range, ent_coef=rl.ent_coef, gamma=rl.gamma,
                            gae_lambda=rl.gae_lambda, seed=seed, device=rl.device, verbose=0,
                            policy_kwargs={"net_arch": {"pi": list(rl.net_arch), "vf": list(rl.net_arch)}})
    p0 = _param_vector(model.policy.parameters())
    t_start = time.time()
    wall0 = counters["wall_s"]
    eval_env = eval_factory(seed + 7919) if eval_factory else None

    def save(tag: str, extra=None):
        d = rd / tag
        d.mkdir(parents=True, exist_ok=True)
        model.save(str(d / "policy.zip"))
        counters["wall_s"] = wall0 + time.time() - t_start
        ck.save_meta(d, ck.make_meta(cfg, "ppo", seed, network_version, dict(counters), manifest, extra))
        ck.save_rng(d)

    state = {"stopped_by": None, "next_save": counters["decisions"] + rl.save_every_decisions,
             "next_eval": counters["decisions"] + rl.eval_every_decisions}

    class CB(BaseCallback):
        def _on_step(self) -> bool:
            counters["decisions"] += rl.n_envs
            for s in _summaries(self.locals.get("infos", [])):
                counters["episodes"] += 1
                log(event="episode", decisions=counters["decisions"], summary=s,
                    vehicle_hours=s.get("in_scope_vehicle_hours"), scenario=s.get("scenario"))
            if counters["decisions"] >= state["next_save"]:
                save("latest")
                state["next_save"] += rl.save_every_decisions
            if counters["decisions"] >= rl.max_decisions:
                state["stopped_by"] = "max_decisions"
                return False
            if (wall0 + time.time() - t_start) / 3600 >= rl.wall_hours:
                state["stopped_by"] = "wall_hours"
                return False
            return True

        def _on_rollout_end(self) -> None:
            if eval_env is None or counters["decisions"] < state["next_eval"]:
                return
            state["next_eval"] += rl.eval_every_decisions
            infos = []
            rets, lens = evaluate_policy(model, eval_env, n_eval_episodes=rl.eval_episodes, deterministic=True,
                                         use_masking=True, return_episode_rewards=True,
                                         callback=lambda l, g: infos.append(l.get("info")) if l.get("done") else None)
            m = float(np.mean(rets))
            log(event="validation", decisions=counters["decisions"], mean_return=m, returns=rets,
                summaries=_summaries(infos))
            if counters["best_val_return"] is None or m > counters["best_val_return"]:
                counters["best_val_return"] = m
                save("best", {"validation": {"mean_return": m, "returns": rets}})

    remaining = max(rl.max_decisions - counters["decisions"], 0)
    try:
        if remaining:
            model.learn(total_timesteps=remaining, callback=CB(), reset_num_timesteps=not resume, progress_bar=False)
        state["stopped_by"] = state["stopped_by"] or "max_decisions"
    finally:
        save("latest")
        venv.close()
        if eval_env is not None:
            eval_env.close()
    change = float(np.linalg.norm(_param_vector(model.policy.parameters()) - p0))
    summ = {"algo": "ppo", "seed": seed, **counters, "stopped_by": state["stopped_by"], "param_change_l2": change,
            "policy_updates": int(getattr(model, "_n_updates", 0)), "run_dir": str(rd),
            "note": "a pilot budget; reaching it is not convergence"}
    (rd / "summary.json").write_text(json.dumps(summ, indent=1, default=str))
    log(event="done", **{k: v for k, v in summ.items()})
    log.close()
    return summ


def train_ddqn(cfg: Config, seed: int, env_factory, eval_factory, network_version: str, manifest: dict,
               resume: bool = False, name: str | None = None) -> dict:
    from .ddqn import MaskedDDQN

    rl = cfg.rl
    rd = run_dir(cfg, "ddqn", seed, name)
    log = Log(rd)
    env = env_factory(seed)
    counters = {"decisions": 0, "episodes": 0, "wall_s": 0.0, "best_val_return": None}
    if resume and (rd / "latest" / "ddqn.pt").exists():
        meta = ck.load_meta(rd / "latest")
        probs = ck.problems(meta, cfg, network_version)
        if probs:
            raise SystemExit("cannot resume (replay would mix feature/forecaster versions): " + "; ".join(probs))
        agent = MaskedDDQN.load(rd / "latest", rl, rl.device)
        ck.load_rng(rd / "latest")
        counters.update(meta["counters"])
        log(event="resumed", from_decisions=counters["decisions"], note="episode-boundary restart")
    else:
        agent = MaskedDDQN(feat.obs_dim(rl.k), rl.k, rl, seed, rl.device)
    p0 = _param_vector(agent.q.parameters())
    eval_env = eval_factory(seed + 7919) if eval_factory else None
    t_start, wall0 = time.time(), counters["wall_s"]
    next_save = counters["decisions"] + rl.save_every_decisions
    next_eval = counters["decisions"] + rl.eval_every_decisions

    def save(tag, extra=None):
        d = rd / tag
        agent.save(d, with_replay=(tag == "latest"))
        counters["wall_s"] = wall0 + time.time() - t_start
        ck.save_meta(d, ck.make_meta(cfg, "ddqn", seed, network_version, dict(counters), manifest, extra))
        ck.save_rng(d)

    stopped = None
    losses: list[float] = []
    if rl.n_envs > 1:
        env.close()
        return _train_ddqn_vec(cfg, seed, env_factory, eval_env, agent, rd, log, counters, p0, save, t_start, wall0,
                               next_save, next_eval)
    try:
        while stopped is None:
            obs, info = env.reset()
            if info.get("empty_episode"):
                counters["episodes"] += 1
                continue
            done = False
            while not done:
                mask = env.action_masks()
                a = agent.act(obs, mask, explore=True)
                nobs, r, term, trunc, info = env.step(a)
                loss = agent.observe(obs, a, r, nobs, term, trunc, info["action_mask"])
                if loss is not None:
                    losses.append(loss)
                obs, done = nobs, term or trunc
                counters["decisions"] += 1
                if counters["decisions"] >= next_save:
                    save("latest")
                    next_save += rl.save_every_decisions
                if counters["decisions"] >= rl.max_decisions:
                    stopped = "max_decisions"
                elif (wall0 + time.time() - t_start) / 3600 >= rl.wall_hours:
                    stopped = "wall_hours"
                if stopped and not done:
                    log(event="stopped_mid_episode", decisions=counters["decisions"])
                    env.close()
                    break
            for s in _summaries([info]):
                counters["episodes"] += 1
                log(event="episode", decisions=counters["decisions"], epsilon=agent.epsilon(),
                    mean_loss=float(np.mean(losses[-200:])) if losses else None,
                    vehicle_hours=s.get("in_scope_vehicle_hours"), scenario=s.get("scenario"), summary=s)
            if eval_env is not None and counters["decisions"] >= next_eval:
                next_eval += rl.eval_every_decisions
                res = run_episodes(eval_env, agent.greedy, rl.eval_episodes)
                m = float(np.mean([x["return"] for x in res]))
                log(event="validation", decisions=counters["decisions"], mean_return=m,
                    summaries=[x["summary"] for x in res])
                if counters["best_val_return"] is None or m > counters["best_val_return"]:
                    counters["best_val_return"] = m
                    save("best", {"validation": {"mean_return": m}})
    finally:
        save("latest")
        env.close()
        if eval_env is not None:
            eval_env.close()
    change = float(np.linalg.norm(_param_vector(agent.q.parameters()) - p0))
    summ = {"algo": "ddqn", "seed": seed, **counters, "stopped_by": stopped, "param_change_l2": change,
            "updates": agent.updates, "epsilon": agent.epsilon(), "run_dir": str(rd),
            "note": "a pilot budget; reaching it is not convergence"}
    (rd / "summary.json").write_text(json.dumps(summ, indent=1, default=str))
    log(event="done", **summ)
    log.close()
    return summ


def _train_ddqn_vec(cfg, seed, env_factory, eval_env, agent, rd, log, counters, p0, save, t_start, wall0,
                    next_save, next_eval) -> dict:
    """Masked Double DQN with `rl.n_envs` parallel actors (SB3 SubprocVecEnv) sharing one agent and one replay.
    Every transition keeps the actor's own terminal/truncation flags and next-state mask; an auto-reset actor's
    transition uses its terminal observation, never the next episode's first state."""
    from stable_baselines3.common.vec_env import SubprocVecEnv

    rl = cfg.rl
    venv = SubprocVecEnv([lambda i=i: env_factory(seed + 1000 * i) for i in range(rl.n_envs)], start_method="spawn")
    stopped = None
    losses: list[float] = []
    try:
        obs = venv.reset()
        masks = np.stack(venv.env_method("action_masks"))
        while stopped is None:
            acts = np.array([agent.act(obs[i], masks[i], explore=True) for i in range(rl.n_envs)])
            nobs, rews, dones, infos = venv.step(acts)
            nmasks = np.stack(venv.env_method("action_masks"))
            for i in range(rl.n_envs):
                trunc = bool(dones[i] and infos[i].get("TimeLimit.truncated", False))
                term = bool(dones[i]) and not trunc
                nxt = infos[i]["terminal_observation"] if dones[i] else nobs[i]
                loss = agent.observe(obs[i], int(acts[i]), float(rews[i]), nxt, term, trunc, infos[i]["action_mask"])
                if loss is not None:
                    losses.append(loss)
                counters["decisions"] += 1
                for s in _summaries([infos[i]]):
                    counters["episodes"] += 1
                    log(event="episode", decisions=counters["decisions"], epsilon=agent.epsilon(),
                        mean_loss=float(np.mean(losses[-200:])) if losses else None,
                        vehicle_hours=s.get("in_scope_vehicle_hours"), scenario=s.get("scenario"), summary=s)
            obs, masks = nobs, nmasks
            if counters["decisions"] >= next_save:
                save("latest")
                next_save += rl.save_every_decisions
            if counters["decisions"] >= rl.max_decisions:
                stopped = "max_decisions"
            elif (wall0 + time.time() - t_start) / 3600 >= rl.wall_hours:
                stopped = "wall_hours"
            if eval_env is not None and counters["decisions"] >= next_eval:
                next_eval += rl.eval_every_decisions
                res = run_episodes(eval_env, agent.greedy, rl.eval_episodes)
                m = float(np.mean([x["return"] for x in res]))
                log(event="validation", decisions=counters["decisions"], mean_return=m,
                    summaries=[x["summary"] for x in res])
                if counters["best_val_return"] is None or m > counters["best_val_return"]:
                    counters["best_val_return"] = m
                    save("best", {"validation": {"mean_return": m}})
        log(event="stopped_mid_episode", decisions=counters["decisions"], actors=rl.n_envs,
            note="in-flight actor episodes are abandoned at the budget")
    finally:
        save("latest")
        venv.close()
        if eval_env is not None:
            eval_env.close()
    change = float(np.linalg.norm(_param_vector(agent.q.parameters()) - p0))
    summ = {"algo": "ddqn", "seed": seed, **counters, "stopped_by": stopped, "param_change_l2": change,
            "updates": agent.updates, "epsilon": agent.epsilon(), "actors": rl.n_envs, "run_dir": str(rd),
            "note": "a pilot budget; reaching it is not convergence"}
    (rd / "summary.json").write_text(json.dumps(summ, indent=1, default=str))
    log(event="done", **summ)
    log.close()
    return summ
