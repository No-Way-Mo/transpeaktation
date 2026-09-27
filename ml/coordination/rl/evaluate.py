"""Episode runners for validation and the environment gate. All action functions receive the mask and may only
return a valid slot."""
from __future__ import annotations

import time

import numpy as np


def act_fastest(obs, mask) -> int:
    return int(np.flatnonzero(mask)[0])             # slot order = forecast ETA, so the first valid slot is fastest


def act_alternative(obs, mask) -> int:
    return int(np.flatnonzero(mask)[-1])            # the slowest valid candidate: deliberately different routes


def act_random(seed: int):
    rng = np.random.default_rng(seed)
    return lambda obs, mask: int(rng.choice(np.flatnonzero(mask)))


def run_episodes(env, act, n: int = 1, options: list | None = None) -> list[dict]:
    out = []
    for e in range(n):
        t0 = time.perf_counter()
        obs, info = env.reset(options=(options[e] if options else None))
        ret, steps = 0.0, 0
        if info.get("empty_episode"):
            out.append({"return": 0.0, "decisions": 0, "summary": info.get("episode_summary"), "wall_s": 0.0})
            continue
        done = False
        while not done:
            obs, r, term, trunc, info = env.step(act(obs, env.action_masks()))
            ret += r
            steps += 1
            done = term or trunc
        out.append({"return": ret, "decisions": steps, "terminated": term, "truncated": trunc,
                    "summary": info.get("episode_summary"), "wall_s": time.perf_counter() - t0})
    return out
