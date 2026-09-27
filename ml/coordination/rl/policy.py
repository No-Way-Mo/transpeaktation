"""Loaded policies for inference (selector + evaluation). Cached per checkpoint identity: a checkpoint is loaded once
per process, and replacing it (new meta.json) is picked up explicitly by identity, never by reloading per request."""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from .checkpoint import load_meta

_CACHE: dict = {}
LOADS = {"count": 0}


def identity(d: Path) -> str:
    d = Path(d)
    h = hashlib.sha1((d / "meta.json").read_bytes())
    for f in ("policy.zip", "ddqn.pt", "appo.pt"):
        if (d / f).exists():
            st = (d / f).stat()
            h.update(f"{f}:{st.st_size}:{st.st_mtime_ns}".encode())
    return h.hexdigest()[:16]


class Policy:
    def __init__(self, d: Path, device: str = "cpu"):
        self.dir = Path(d)
        self.meta = load_meta(self.dir)
        self.algo = self.meta["algo"]
        self.id = identity(self.dir)
        if self.algo == "ppo":
            from sb3_contrib import MaskablePPO
            self.model = MaskablePPO.load(str(self.dir / "policy.zip"), device=device)
        elif self.algo == "ddqn":
            import torch
            from .ddqn import QNet
            s = torch.load(self.dir / "ddqn.pt", map_location=device, weights_only=False)
            self.q = QNet(s["obs_dim"], s["k"], tuple(s.get("hidden", (128, 128)))).to(device)
            self.q.load_state_dict(s["q"])
            self.q.eval()
            self.device = device
        elif self.algo == "appo":
            import torch
            from .async_train import ActorCritic
            s = torch.load(self.dir / "appo.pt", map_location=device, weights_only=False)
            self.net = ActorCritic(s["obs_dim"], s["k"], tuple(s["hidden"])).to(device)
            self.net.load_state_dict(s["net"])
            self.net.eval()
            self.device = device
        else:
            raise ValueError(f"unknown algo {self.algo!r}")
        LOADS["count"] += 1

    def act(self, obs: np.ndarray, mask: np.ndarray) -> int:
        """Deterministic masked action."""
        mask = np.asarray(mask, bool)
        if not mask.any():
            raise ValueError("all-invalid mask")
        if self.algo == "ppo":
            a, _ = self.model.predict(obs, action_masks=mask, deterministic=True)
            a = int(a)
        elif self.algo == "appo":
            import torch
            from .ddqn import masked_argmax
            with torch.no_grad():
                logits, _ = self.net(torch.as_tensor(obs, dtype=torch.float32, device=self.device)[None])
                a = int(masked_argmax(logits, torch.as_tensor(mask, device=self.device)[None])[0])
        else:
            import torch
            from .ddqn import masked_argmax
            with torch.no_grad():
                q = self.q(torch.as_tensor(obs, dtype=torch.float32, device=self.device)[None])
                a = int(masked_argmax(q, torch.as_tensor(mask, device=self.device)[None])[0])
        if not mask[a]:
            raise RuntimeError(f"policy proposed masked action {a}")
        return a


def load(d, device: str = "cpu") -> Policy:
    d = Path(d)
    key = (str(d.resolve()), identity(d), device)
    if key not in _CACHE:
        _CACHE[key] = Policy(d, device)
    return _CACHE[key]
