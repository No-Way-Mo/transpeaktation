"""Policy D: learned route selection (MaskablePPO or masked Double DQN checkpoint).

* Lazy optional imports: serving with other selectors never loads torch/SB3.
* The checkpoint is loaded once and cached by identity (rl/policy.py); the selector instance itself is cached by
  the coordinator. A missing or incompatible checkpoint raises SelectorUnavailable: in normal serving the
  coordinator falls back to the heuristic and says so; in strict mode (benchmarks) that is an explicit failure.
* Requests of a batch are processed in recorded order with a temporary extra-load overlay after each choice (like
  the heuristic). The real ledger is never mutated here.
* Diagnostics carry the checkpoint identity and the chosen slot; they are not a claim of congestion reduction.
"""
from __future__ import annotations

import time
from pathlib import Path

from ..schemas import SelectionContext, SelectionResult
from .base import Selector, SelectorUnavailable, valid_indices


class RL(Selector):
    name = "rl"
    version = "rl-unavailable"

    def __init__(self, cfg=None, checkpoint: str | None = None):
        self.cfg = cfg
        self.checkpoint = checkpoint if checkpoint is not None else (cfg.rl.checkpoint if cfg is not None else "")
        self._policy = None
        self._checked = None

    def _load(self, ctx: SelectionContext):
        if not self.checkpoint:
            raise SelectorUnavailable("rl_not_trained: no checkpoint configured (rl.checkpoint)")
        d = self.cfg.path(self.checkpoint) if self.cfg is not None else Path(self.checkpoint)
        if not (d / "meta.json").exists():
            raise SelectorUnavailable(f"rl_not_trained: no checkpoint at {d}")
        try:
            from ..rl import checkpoint as ck
            from ..rl import policy as pol
        except ImportError as e:
            raise SelectorUnavailable(f"rl dependencies missing: {e}")
        pid = pol.identity(d)
        if self._policy is None or self._policy.id != pid:
            meta = ck.load_meta(d)
            probs = ck.problems(meta, self.cfg, ctx.net.version if ctx.net is not None else "")
            if probs:
                raise SelectorUnavailable("incompatible_checkpoint: " + "; ".join(probs))
            self._policy = pol.load(d, self.cfg.rl.device)
            self.version = f"rl_{self._policy.algo}-{self._policy.id}"
        return self._policy

    def select(self, ctx: SelectionContext) -> SelectionResult:
        from ..rl import features as feat
        t0 = time.perf_counter()
        policy = self._load(ctx)
        res = SelectionResult(choices={}, policy=self.name, policy_version=self.version)
        extra: dict = {}
        for i, item in enumerate(ctx.items):
            rid = item.request.request_id
            idx = valid_indices(item)
            if not idx:
                res.reasons[rid] = ["no_valid_candidate"]
                continue
            if len(idx) == 1:
                k = idx[0]
                res.reasons[rid] = ["single_candidate"]
            else:
                obs, mask = feat.encode(ctx, i, extra, self.cfg.rl.k)
                k = policy.act(obs, mask)
                fastest = min(idx, key=lambda j: (item.candidates[j].eta_s, item.candidates[j].candidate_id))
                res.reasons[rid] = ["policy_choice_fastest" if k == fastest else "policy_choice_alternative"]
            res.choices[rid] = k
            res.diagnostics[rid] = {"checkpoint": policy.id, "algo": policy.algo, "slot": k}
            for c, w in item.candidates[k].cells.items():
                extra[c] = extra.get(c, 0.0) + w
        res.runtime_ms = (time.perf_counter() - t0) * 1000
        return res
