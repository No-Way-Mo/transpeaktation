"""Masked Double DQN (RL_ROUTING_RESEARCH_AND_PLAN.md §8). SB3's DQN is vanilla DQN, so this is a small explicit
implementation.

* Online and target Q networks: MLP obs -> 128 -> 128 -> K. Uniform replay. Hard target updates.
* Masks everywhere: epsilon-greedy explores ONLY valid slots; greedy acts by masked argmax; the bootstrap target
  selects a* = masked argmax of the ONLINE net on the next state and evaluates it with the TARGET net (Double DQN).
* Terminal transitions never bootstrap. A next state with no valid slot (e.g. the drain transition after the last
  decision) never bootstraps either: there is no argmax over all-invalid slots. A truncated transition WITH valid
  next slots bootstraps (truncation is not an outcome). Censored cost at a drain cap is reported by the env, not
  invented here.
* Replay stores obs, action, reward, next obs, terminated, truncated and the next action mask. Clear/segregate it if
  the feature schema or forecaster changes (checkpoint.py refuses to resume across schema changes).
"""
from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

NEG = -1e9


class QNet(nn.Module):
    def __init__(self, obs_dim: int, k: int, hidden=(128, 128)):
        super().__init__()
        layers, d = [], obs_dim
        for h in hidden:
            layers += [nn.Linear(d, h), nn.ReLU()]
            d = h
        layers.append(nn.Linear(d, k))
        self.net = nn.Sequential(*layers)

    def forward(self, x):
        return self.net(x)


def masked_argmax(q: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    return torch.where(mask, q, torch.full_like(q, NEG)).argmax(-1)


class Replay:
    def __init__(self, capacity: int, obs_dim: int, k: int):
        self.cap, self.n, self.i = capacity, 0, 0
        self.obs = np.zeros((capacity, obs_dim), np.float32)
        self.next_obs = np.zeros((capacity, obs_dim), np.float32)
        self.act = np.zeros(capacity, np.int64)
        self.rew = np.zeros(capacity, np.float32)
        self.term = np.zeros(capacity, bool)
        self.trunc = np.zeros(capacity, bool)
        self.next_mask = np.zeros((capacity, k), bool)

    def add(self, obs, act, rew, next_obs, terminated, truncated, next_mask):
        j = self.i
        self.obs[j], self.act[j], self.rew[j], self.next_obs[j] = obs, act, rew, next_obs
        self.term[j], self.trunc[j], self.next_mask[j] = terminated, truncated, next_mask
        self.i = (self.i + 1) % self.cap
        self.n = min(self.n + 1, self.cap)

    def sample(self, batch: int, rng: np.random.Generator) -> dict:
        idx = rng.integers(0, self.n, size=batch)
        return {k: getattr(self, k)[idx] for k in ("obs", "act", "rew", "next_obs", "term", "trunc", "next_mask")}

    def state(self) -> dict:
        n = self.n
        return {"n": n, "i": self.i, **{k: getattr(self, k)[:n] if self.n < self.cap else getattr(self, k)
                                       for k in ("obs", "act", "rew", "next_obs", "term", "trunc", "next_mask")}}

    def load_state(self, s: dict) -> None:
        n = int(s["n"])
        for k in ("obs", "act", "rew", "next_obs", "term", "trunc", "next_mask"):
            getattr(self, k)[:len(s[k])] = s[k]
        self.n, self.i = n, int(s["i"])


class MaskedDDQN:
    algo = "ddqn"

    def __init__(self, obs_dim: int, k: int, rl_cfg, seed: int = 0, device: str = "cpu"):
        self.obs_dim, self.k, self.c = obs_dim, k, rl_cfg
        self.device = torch.device(device)
        torch.manual_seed(seed)
        self.q = QNet(obs_dim, k).to(self.device)
        self.q_target = copy.deepcopy(self.q)
        self.opt = torch.optim.Adam(self.q.parameters(), lr=rl_cfg.dqn_lr)
        self.replay = Replay(rl_cfg.buffer_size, obs_dim, k)
        self.rng = np.random.default_rng(seed)
        self.decisions = 0
        self.updates = 0
        self.gamma = rl_cfg.gamma

    # ---- acting ------------------------------------------------------------------------------------------------------
    def epsilon(self) -> float:
        c = self.c
        f = min(1.0, self.decisions / max(c.eps_decay_decisions, 1))
        return c.eps_start + f * (c.eps_end - c.eps_start)

    @torch.no_grad()
    def greedy(self, obs: np.ndarray, mask: np.ndarray) -> int:
        mask = np.asarray(mask, bool)
        if not mask.any():
            raise ValueError("all-invalid mask: no-route requests are handled outside the policy")
        q = self.q(torch.as_tensor(obs, dtype=torch.float32, device=self.device)[None])
        return int(masked_argmax(q, torch.as_tensor(mask, device=self.device)[None])[0])

    def act(self, obs: np.ndarray, mask: np.ndarray, explore: bool = True) -> int:
        mask = np.asarray(mask, bool)
        if not mask.any():
            raise ValueError("all-invalid mask: no-route requests are handled outside the policy")
        if explore and self.rng.random() < self.epsilon():
            return int(self.rng.choice(np.flatnonzero(mask)))
        return self.greedy(obs, mask)

    # ---- learning ----------------------------------------------------------------------------------------------------
    def td_target(self, rew, next_obs, next_mask, term, trunc) -> torch.Tensor:
        with torch.no_grad():
            has_next = next_mask.any(-1)
            boot = (~term) & has_next                      # truncated-with-valid-next bootstraps; terminal never
            a_star = masked_argmax(self.q(next_obs), next_mask)
            q_next = self.q_target(next_obs).gather(1, a_star[:, None])[:, 0]
            return rew + self.gamma * boot.float() * q_next

    def update(self) -> float:
        b = self.replay.sample(self.c.dqn_batch_size, self.rng)
        t = lambda a, dt=torch.float32: torch.as_tensor(a, dtype=dt, device=self.device)
        obs, next_obs = t(b["obs"]), t(b["next_obs"])
        act = t(b["act"], torch.int64)
        y = self.td_target(t(b["rew"]), next_obs, t(b["next_mask"], torch.bool), t(b["term"], torch.bool),
                           t(b["trunc"], torch.bool))
        q = self.q(obs).gather(1, act[:, None])[:, 0]
        loss = F.smooth_l1_loss(q, y)
        self.opt.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self.q.parameters(), self.c.grad_clip)
        self.opt.step()
        self.updates += 1
        if self.updates % self.c.target_update == 0:
            self.q_target.load_state_dict(self.q.state_dict())
        return float(loss)

    def observe(self, obs, act, rew, next_obs, terminated, truncated, next_mask) -> float | None:
        """Store one transition, maybe train. Returns the loss when an update ran."""
        self.replay.add(obs, act, rew, next_obs, terminated, truncated, next_mask)
        self.decisions += 1
        if self.decisions >= self.c.learning_starts and self.decisions % self.c.train_freq == 0 \
                and self.replay.n >= self.c.dqn_batch_size:
            return self.update()
        return None

    # ---- persistence -------------------------------------------------------------------------------------------------
    def save(self, d: Path, with_replay: bool = True) -> None:
        d.mkdir(parents=True, exist_ok=True)
        torch.save({"q": self.q.state_dict(), "q_target": self.q_target.state_dict(), "opt": self.opt.state_dict(),
                    "decisions": self.decisions, "updates": self.updates, "obs_dim": self.obs_dim, "k": self.k,
                    "rng": self.rng.bit_generator.state, "torch_rng": torch.get_rng_state()}, d / "ddqn.pt")
        if with_replay:
            np.savez_compressed(d / "replay.npz", **self.replay.state())

    @classmethod
    def load(cls, d: Path, rl_cfg, device: str = "cpu", with_replay: bool = True) -> "MaskedDDQN":
        s = torch.load(d / "ddqn.pt", map_location=device, weights_only=False)
        agent = cls(s["obs_dim"], s["k"], rl_cfg, device=device)
        agent.q.load_state_dict(s["q"])
        agent.q_target.load_state_dict(s["q_target"])
        agent.opt.load_state_dict(s["opt"])
        agent.decisions, agent.updates = s["decisions"], s["updates"]
        agent.rng.bit_generator.state = s["rng"]
        torch.set_rng_state(s["torch_rng"])
        if with_replay and (d / "replay.npz").exists():
            with np.load(d / "replay.npz") as z:
                agent.replay.load_state({k: z[k] for k in z.files})
        return agent
