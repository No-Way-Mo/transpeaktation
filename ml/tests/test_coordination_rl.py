"""RL components without SUMO (python -m unittest tests.test_coordination_rl): features, masked Double DQN targets,
MaskablePPO / DDQN trainers on a toy masked environment, checkpoints, the RL selector in the coordinator."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

try:
    import gymnasium as gym
    import sb3_contrib  # noqa: F401
    import torch
    HAVE = True
except ImportError:
    HAVE = False

from coordination.config import Config
from coordination.schemas import RouteRequest
from tests.test_coordination import T0, coord, diamond, forecast_df, make_net, mid, rid
from coordination.forecast_store import validate


def small_cfg(d: Path) -> Config:
    cfg = Config()
    cfg.rl.run_dir = str(d / "runs")
    cfg.rl.n_steps = 64
    cfg.rl.batch_size = 32
    cfg.rl.n_epochs = 4
    cfg.rl.save_every_decisions = 200
    cfg.rl.eval_every_decisions = 10**9
    cfg.rl.learning_starts = 64
    cfg.rl.dqn_batch_size = 32
    cfg.rl.target_update = 50
    cfg.rl.eps_decay_decisions = 600
    cfg.rl.dqn_lr = 1e-3
    cfg.rl.ppo_lr = 1e-3
    cfg.env.forecast_mode = "fixture_debug"
    return cfg


if HAVE:
    from coordination.rl import features as feat

    class ToyMaskedEnv(gym.Env):
        """Same observation/action shape as the real env. Slot j's `eta_per_10min` feature is its cost; the best
        valid slot minimises it. Random masks with >= 2 valid slots; 8 decisions per episode."""

        def __init__(self, seed=0):
            self.K = 5
            self.F = len(feat.CAND_FEATURES)
            self.observation_space = gym.spaces.Box(-np.inf, np.inf, (feat.obs_dim(self.K),), np.float32)
            self.action_space = gym.spaces.Discrete(self.K)
            self.rng = np.random.default_rng(seed)
            self.eta_i = feat.CAND_FEATURES.index("eta_per_10min")

        def _draw(self):
            self.mask = self.rng.random(self.K) < 0.7
            self.mask[self.rng.choice(self.K, 2, replace=False)] = True
            self.cost = self.rng.random(self.K)
            obs = np.zeros(self.observation_space.shape, np.float32)
            for j in range(self.K):
                if self.mask[j]:
                    obs[j * self.F] = 1.0
                    obs[j * self.F + self.eta_i] = self.cost[j]
            self.obs = obs
            return obs

        def action_masks(self):
            return self.mask.copy()

        def reset(self, *, seed=None, options=None):
            super().reset(seed=seed)
            self.n = 0
            return self._draw(), {"action_mask": self.mask.copy()}

        def step(self, a):
            assert self.mask[a], "masked action applied"
            r = -float(self.cost[a])
            self.n += 1
            done = self.n >= 8
            if done:
                self.mask = np.zeros(self.K, bool)
                return np.zeros_like(self.obs), r, True, False, {"action_mask": self.mask.copy(),
                                                                  "episode_summary": {"toy": True}}
            return self._draw(), r, False, False, {"action_mask": self.mask.copy()}

    def greedy_accuracy(act, n=300, seed=123):
        env = ToyMaskedEnv(seed)
        env.reset()
        hit = 0
        for _ in range(n):
            obs = env._draw()
            a = act(obs, env.mask)
            valid = np.flatnonzero(env.mask)
            hit += int(a == valid[np.argmin(env.cost[valid])])
        return hit / n


@unittest.skipUnless(HAVE, "rl dependencies not installed")
class TestMaskedDDQN(unittest.TestCase):
    def setUp(self):
        from coordination.rl.ddqn import MaskedDDQN
        self.cfg = Config().rl
        self.agent = MaskedDDQN(6, 3, self.cfg, seed=0)

    def test_exploration_only_valid(self):
        mask = np.array([False, True, False])
        self.agent.decisions = 0                    # epsilon = 1: pure exploration
        for _ in range(50):
            self.assertEqual(self.agent.act(np.zeros(6, np.float32), mask, explore=True), 1)
        with self.assertRaises(ValueError):
            self.agent.act(np.zeros(6, np.float32), np.zeros(3, bool))

    def test_double_q_target_masked_terminal_and_truncation(self):
        a = self.agent
        with torch.no_grad():
            for p in list(a.q.parameters()) + list(a.q_target.parameters()):
                p.zero_()
            a.q.net[-1].bias[:] = torch.tensor([100.0, 1.0, 2.0])          # online prefers slot 0 (masked below)
            a.q_target.net[-1].bias[:] = torch.tensor([-50.0, 10.0, 20.0])
        nobs = torch.zeros(4, 6)
        mask = torch.tensor([[False, True, True], [False, True, True], [False, True, True], [False, False, False]])
        term = torch.tensor([False, True, False, False])
        trunc = torch.tensor([False, False, True, True])
        y = a.td_target(torch.ones(4), nobs, mask, term, trunc).numpy()
        # nonterminal: online masked argmax = slot 2, evaluated by the TARGET net = 20 (not 100, not max target)
        self.assertAlmostEqual(y[0], 1 + a.gamma * 20.0)
        self.assertAlmostEqual(y[1], 1.0)                                    # terminal: no bootstrap
        self.assertAlmostEqual(y[2], 1 + a.gamma * 20.0)                    # truncated with valid next: bootstrap
        self.assertAlmostEqual(y[3], 1.0)                                    # no valid next slot: no bootstrap

    def test_replay_roundtrip(self):
        from coordination.rl.ddqn import MaskedDDQN
        a = self.agent
        for i in range(10):
            a.observe(np.full(6, i, np.float32), i % 3, -i, np.zeros(6, np.float32), i == 9, False,
                      np.array([True, True, False]))
        with tempfile.TemporaryDirectory() as d:
            a.save(Path(d))
            b = MaskedDDQN.load(Path(d), self.cfg)
            self.assertEqual(b.replay.n, 10)
            np.testing.assert_array_equal(b.replay.obs[:10], a.replay.obs[:10])
            self.assertEqual(b.decisions, a.decisions)


@unittest.skipUnless(HAVE, "rl dependencies not installed")
class TestTrainers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_ppo_trains_changes_params_and_roundtrips(self):
        from coordination.rl import policy as pol
        from coordination.rl.train import train_ppo
        cfg = small_cfg(self.tmp)
        cfg.rl.max_decisions = 3000
        cfg.rl.gamma = cfg.rl.gae_lambda = 0.0     # the toy is a contextual bandit (independent steps)
        s = train_ppo(cfg, 0, lambda sd: ToyMaskedEnv(sd), None, "toy-net", {"toy": True}, name="ppo_toy")
        self.assertEqual(s["stopped_by"], "max_decisions")
        self.assertGreater(s["param_change_l2"], 0.0)
        self.assertGreater(s["episodes"], 0)
        p = pol.load(Path(s["run_dir"]) / "latest")
        acc = greedy_accuracy(p.act)
        self.assertGreater(acc, 0.55, f"PPO greedy accuracy {acc:.2f} on the toy task")  # random ~ 0.3
        p2 = pol.Policy(Path(s["run_dir"]) / "latest")                                     # fresh load, same actions
        env = ToyMaskedEnv(5)
        env.reset()
        for _ in range(20):
            o = env._draw()
            self.assertEqual(p.act(o, env.mask), p2.act(o, env.mask))
        # resume continues from the saved counters
        cfg.rl.max_decisions = 3200
        s2 = train_ppo(cfg, 0, lambda sd: ToyMaskedEnv(sd), None, "toy-net", {"toy": True}, resume=True, name="ppo_toy")
        self.assertGreaterEqual(s2["decisions"], 3200)

    def test_ddqn_trains_and_greedy_improves(self):
        from coordination.rl import policy as pol
        from coordination.rl.train import train_ddqn
        cfg = small_cfg(self.tmp)
        cfg.rl.max_decisions = 2500
        s = train_ddqn(cfg, 0, lambda sd: ToyMaskedEnv(sd), None, "toy-net", {"toy": True}, name="ddqn_toy")
        self.assertEqual(s["stopped_by"], "max_decisions")
        self.assertGreater(s["updates"], 0)
        self.assertGreater(s["param_change_l2"], 0.0)
        acc = greedy_accuracy(pol.load(Path(s["run_dir"]) / "latest").act)
        self.assertGreater(acc, 0.55, f"DDQN greedy accuracy {acc:.2f} on the toy task")

    def test_wall_cap_leaves_usable_checkpoint(self):
        from coordination.rl.train import train_ddqn
        cfg = small_cfg(self.tmp)
        cfg.rl.max_decisions = 10**7
        cfg.rl.wall_hours = 2 / 3600                 # two seconds
        s = train_ddqn(cfg, 1, lambda sd: ToyMaskedEnv(sd), None, "toy-net", {"toy": True}, name="ddqn_wall")
        self.assertEqual(s["stopped_by"], "wall_hours")
        self.assertTrue((Path(s["run_dir"]) / "latest" / "ddqn.pt").exists())


@unittest.skipUnless(HAVE, "rl dependencies not installed")
class TestFeaturesAndSelector(unittest.TestCase):
    def setUp(self):
        self.nodes, roads = diamond()
        self.net = make_net(self.nodes, roads)
        slow = {rid("s", "b"): 1.08, rid("b", "t"): 1.08}
        self.snap = validate(forecast_df(self.net, factor=slow), None, self.net)
        self.o, self.d = mid(self.nodes, "s0", "s", 0.5), mid(self.nodes, "t", "t1", 0.5)
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ctx_for(self, c, n=1):
        items = [c.prepare_request(RouteRequest(f"r{i}", self.o, self.d, c.clock())) for i in range(n)]
        return c.selection_context(items)

    def test_padding_mask_and_shape(self):
        c = coord(self.net, self.snap)
        ctx = self.ctx_for(c)
        obs, mask = feat.encode(ctx, 0, None, 5)
        self.assertEqual(obs.shape, (feat.obs_dim(5),))
        self.assertEqual(mask.tolist(), [True, True, False, False, False])
        F = len(feat.CAND_FEATURES)
        self.assertTrue(np.all(obs[2 * F:5 * F] == 0))                     # padded slots are zero
        self.assertTrue(np.all(np.isfinite(obs)))

    def test_no_future_forecast_allowed(self):
        c = coord(self.net, self.snap)
        ctx = self.ctx_for(c)
        ctx.now = self.snap.issued_at - 60
        with self.assertRaises(feat.LeakageError):
            feat.encode(ctx, 0, None, 5)

    def test_overlay_changes_load_features(self):
        c = coord(self.net, self.snap)
        ctx = self.ctx_for(c)
        o0, _ = feat.encode(ctx, 0, None, 5)
        overlay = {cell: 5.0 for cell in ctx.items[0].candidates[0].cells}
        o1, _ = feat.encode(ctx, 0, overlay, 5)
        i = feat.CAND_FEATURES.index("load_ratio_mean")
        self.assertGreater(o1[i], o0[i])

    def _checkpoint(self, cfg):
        from coordination.rl.train import train_ppo
        cfg.rl.max_decisions = 64
        return Path(train_ppo(cfg, 0, lambda sd: ToyMaskedEnv(sd), None, self.net.version, {"toy": True},
                              name="sel")["run_dir"]) / "latest"

    def test_rl_selector_uses_cached_checkpoint_in_coordinator(self):
        from coordination.rl import policy as pol
        cfg = small_cfg(self.tmp)
        d = self._checkpoint(cfg)
        cfg.rl.checkpoint = str(d)
        c = coord(self.net, self.snap, cfg=cfg, selector="rl")
        before = pol.LOADS["count"]
        res = [c.recommend(RouteRequest(f"u{i}", self.o, self.d, c.clock())) for i in range(4)]
        self.assertTrue(all(r["outcome"] == "recommendation" for r in res))
        self.assertTrue(all(r["selector"]["name"] == "rl" and r["selector"]["fallback_reason"] is None for r in res))
        self.assertLessEqual(pol.LOADS["count"] - before, 1)             # loaded once, not per request
        self.assertTrue(res[0]["selector"]["version"].startswith("rl_ppo-"))
        # the same features the selector saw are what the env/trainer encoder produces
        ctx = self.ctx_for(c)
        obs, mask = feat.encode(ctx, 0, None, 5)
        self.assertEqual(pol.load(d).act(obs, mask), c._selector("rl").select(ctx).choices["r0"])

    def test_incompatible_or_missing_checkpoint_is_explicit(self):
        from coordination.coordinator import SelectorFailed
        cfg = small_cfg(self.tmp)
        cfg.rl.checkpoint = str(self.tmp / "nothing")
        c = coord(self.net, self.snap, cfg=cfg, selector="rl")
        r = c.recommend(RouteRequest("x", self.o, self.d, c.clock()))
        self.assertEqual(r["selector"]["name"], "heuristic")
        self.assertIn("rl_not_trained", r["selector"]["fallback_reason"])
        strict = coord(self.net, self.snap, cfg=cfg, selector="rl")
        strict.strict = True
        with self.assertRaises(SelectorFailed):
            strict.recommend(RouteRequest("y", self.o, self.d, strict.clock()))
        # a checkpoint for another network is refused, not used
        d = self._checkpoint(small_cfg(self.tmp))
        import json
        m = json.loads((d / "meta.json").read_text())
        m["network_version"] = "other-net"
        (d / "meta.json").write_text(json.dumps(m))
        cfg.rl.checkpoint = str(d)
        c2 = coord(self.net, self.snap, cfg=cfg, selector="rl")
        r = c2.recommend(RouteRequest("z", self.o, self.d, c2.clock()))
        self.assertIn("incompatible_checkpoint", r["selector"]["fallback_reason"])


if __name__ == "__main__":
    unittest.main()
