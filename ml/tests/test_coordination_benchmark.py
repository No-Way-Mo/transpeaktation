"""Benchmark report, batch-gate discovery and the vectorised Double DQN trainer, without SUMO
(python -m unittest tests.test_coordination_benchmark)."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from coordination.benchmark import report
from coordination.rl.scenario import _gate


def _run(policy, scenario, seed, vh, part=None, status="ok", terminated=True, demand="d", cong=None, **bench):
    return {"policy": policy, "scenario": scenario, "seed_offset": seed, "status": status, "wall_s": 1.0,
            "summary": {"in_scope_vehicle_hours": vh, "invalid_route": 0, "terminated": terminated,
                        "unfinished": 0 if terminated else 3,
                        "congestion": {"congested_h_scope": cong if cong is not None else (vh or 0) / 10},
                        "identity": {"demand_sha": demand, "participants_sha": "p", "noncompliant_sha": "n"},
                        "outcomes": {"participants": {"trip_s_mean": part}, "others": {"trip_s_mean": 100.0}},
                        "bench": {"selector_failures": 0, **bench}}}


class TestReport(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def res(self):
        runs = []
        for sc, base in (("s1", 100.0), ("s2", 200.0)):
            runs += [_run("forecast_only", sc, 0, base, 300.0), _run("heuristic", sc, 0, base - 2, 290.0),
                     _run("batch", sc, 0, base + (1 if sc == "s1" else -1), 295.0),
                     _run("rl_ppo", sc, 0, None, status="unavailable")]
        meta = {"suite": "screening", "scenarios": ["s1", "s2"], "seeds": [0], "policies": ["forecast_only", "heuristic",
                "batch", "rl_ppo"], "forecast_mode": "model", "forecast_checkpoint": "x", "participation": 0.05,
                "compliance": 1.0, "batch_window_s": 60, "checkpoints": {}}
        return {"meta": meta, "runs": runs, "wall_s": 1.0}

    def test_paired_differences_and_verdicts(self):
        df = report.flatten(self.res())
        pv = report.paired(df, "vehicle_hours").set_index("policy")
        self.assertAlmostEqual(pv.loc["heuristic", "mean_diff"], -2.0)
        self.assertEqual(pv.loc["heuristic", "verdict"], "better in every pair")
        self.assertEqual(pv.loc["batch", "verdict"], "inconclusive")          # one better, one worse
        self.assertNotIn("rl_ppo", pv.index)                                 # unavailable runs are not pairs

    def test_best_requires_every_run_ok(self):
        out = report.write(self.res(), self.tmp / "r.md", self.tmp / "r.csv")
        self.assertEqual(out["best"], "heuristic")
        text = (self.tmp / "r.md").read_text(encoding="utf-8")
        self.assertIn("Synthetic", text)
        self.assertIn("| policy |", text)

    def test_incomplete_run_cannot_win_and_block_is_excluded(self):
        res = self.res()
        # heuristic "wins" s1 by leaving vehicles unfinished: the block leaves the primary ranking for every policy
        res["runs"][1] = _run("heuristic", "s1", 0, 50.0, 280.0, terminated=False)
        S = report.summarize(res)
        self.assertEqual(S["blocks"], [("s2", 0)])
        self.assertNotIn("heuristic", S["eligible"])
        self.assertEqual(S["best"], "batch")                               # -1 on s2, and every batch run complete
        report.write(res, self.tmp / "r.md", self.tmp / "r.csv")
        text = (self.tmp / "r.md").read_text(encoding="utf-8")
        self.assertIn("all_in_scope_arrived", text)                       # the failure stays visible

    def test_population_mismatch_excludes_block(self):
        res = self.res()
        res["runs"][2] = _run("batch", "s1", 0, 99.0, 295.0, demand="other")
        S = report.summarize(res)
        self.assertEqual(S["blocks"], [("s2", 0)])
        self.assertEqual(S["population_mismatches"][0]["field"], "demand_sha")

    def test_congestion_metric_paired_and_targets(self):
        S = report.summarize(self.res())
        pv = S["paired"].set_index(["policy", "metric"])
        self.assertAlmostEqual(pv.loc[("heuristic", "congested_h_scope"), "mean_diff"], -0.2)
        t = S["targets"]["heuristic"]
        self.assertTrue(t["lower_congestion"])
        self.assertFalse(t["meets_vehicle_hours_target"])                 # ~1.5% < the 5% target


class TestRunnerPieces(unittest.TestCase):
    def test_policy_variants(self):
        from coordination.benchmark import runner
        from coordination.config import Config
        self.assertEqual(runner.parse_policy("heuristic@lam=120@w=60"), ("heuristic", {"lam": 120.0, "w": 60.0}))
        self.assertEqual(runner.parse_policy("forecast_only@rep=1"), ("forecast_only", {"rep": "1"}))
        with self.assertRaises(SystemExit):
            runner.parse_policy("heuristic@alpha=1")
        cfg = Config()
        c, base, w = runner.policy_setup(cfg, "heuristic@lam=15")
        self.assertEqual((base, w, c.score.lam, cfg.score.lam), ("heuristic", 0.0, 15.0, 60.0))
        self.assertEqual(runner.policy_setup(cfg, "batch")[2], cfg.benchmark.batch_window_s)
        self.assertEqual(runner.policy_setup(cfg, "batch@w=15")[2], 15.0)
        self.assertEqual(runner.policy_setup(cfg, "heuristic@w=60")[2], 60.0)

    def test_quality_flags(self):
        from coordination.benchmark.runner import quality
        good = {"terminated": True, "dropped_trips": 0, "invalid_route": 0, "route_readback_mismatch": 0,
                "forecast_refresh_failures": 0, "bench": {"selector_failures": 0, "unchosen_fallback": 0}}
        self.assertEqual(quality(good), {"complete": True, "failed_checks": []})
        bad = {**good, "terminated": False, "bench": {"unchosen_fallback": 2}}
        self.assertEqual(quality(bad)["failed_checks"], ["all_in_scope_arrived", "no_unchosen_fallbacks"])

    def test_experiment_id_changes_with_config(self):
        from coordination.benchmark import runner
        from coordination.config import Config
        code = {"sources_sha": "x"}
        a = runner.experiment_id(Config(), "screening", ["forecast_only"], ["s"], [0], code)
        self.assertEqual(a, runner.experiment_id(Config(), "screening", ["forecast_only"], ["s"], [0], code))
        c = Config()
        c.env.participation = 0.15
        self.assertNotEqual(a, runner.experiment_id(c, "screening", ["forecast_only"], ["s"], [0], code))
        self.assertNotEqual(a, runner.experiment_id(Config(), "screening", ["forecast_only"], ["s"], [1], code))
        w = Config()
        w.benchmark.workers = 176                                          # execution setting, not an input
        self.assertEqual(a, runner.experiment_id(w, "screening", ["forecast_only"], ["s"], [0], code))


class TestCongestionExposure(unittest.TestCase):
    def test_counts(self):
        import numpy as np
        from coordination.rl.rewards import CongestionExposure
        ff = np.array([10.0, 20.0])                                        # m/s
        e = CongestionExposure(ff, {"a", "b"}, every_s=2.0)
        e.sample(np.array([0]), np.array([1.0]), np.array([True]), 0, 0, 1.0, 1.0)   # before start: ignored
        e.start(1.0)
        # a: road 0 at 4 m/s (<= 5: congested); b: road 1 at 15 (free); c (out of scope): road 1 stopped
        e.sample(np.array([0, 1, 1]), np.array([4.0, 15.0, 0.0]), np.array([True, True, False]), 2, 1, 1.0, 2.0)
        e.sample(np.array([0]), np.array([0.05]), np.array([True]), 0, 0, 1.0, 3.0)
        t = e.tot
        self.assertEqual((t["observed_s_all"], t["congested_s_all"], t["stopped_s_all"]), (4.0, 3.0, 2.0))
        self.assertEqual((t["observed_s_scope"], t["congested_s_scope"], t["stopped_s_scope"]), (3.0, 2.0, 1.0))
        self.assertEqual(t["pending_s_scope"], 2.0)
        self.assertEqual(len(e.series), 1)                                 # one 2 s window flushed at t=3
        self.assertEqual(e.series[0]["arrived_scope"], 1)
        self.assertEqual(list(e.road_congested_s), [2.0, 1.0])
        self.assertAlmostEqual(e.summary()["congested_h_scope"], 2.0 / 3600)


class TestSelectionRule(unittest.TestCase):
    def test_best_and_challenger_from_dev_only(self):
        from coordination.benchmark import backtest
        runs = []
        for sc, base in (("s1", 100.0), ("s2", 200.0)):
            runs += [_run("forecast_only", sc, 0, base), _run("heuristic", sc, 0, base - 1),
                     _run("heuristic@lam=120", sc, 0, base - 3), _run("batch", sc, 0, base - 2),
                     _run("batch@w=15", sc, 0, base + 1)]
        meta = {"suite": "screening", "scenarios": ["s1", "s2"], "seeds": [0], "participation": 0.05,
                "policies": ["forecast_only", "heuristic", "heuristic@lam=120", "batch", "batch@w=15"]}
        adopt = {"meta": {**meta, "participation": 0.3, "policies": ["forecast_only", "heuristic", "batch"]},
                 "runs": [_run("forecast_only", "s1", 0, 100.0), _run("heuristic", "s1", 0, 90.0),
                          _run("batch", "s1", 0, 95.0)]}
        sel = backtest.select({"screen": {"meta": meta, "runs": runs}, "adopt_30": adopt})
        self.assertEqual(sel["best"], "heuristic@lam=120")
        self.assertEqual(sel["challenger"], "batch")                       # best of the other family
        self.assertEqual(sel["dev_adoption_mean_rel_pct"]["heuristic"]["0.3"], -10.0)
        self.assertNotIn("batch@w=15", sel["candidates"])                  # only pre-declared held-out candidates

    def test_partial_and_full_final_report(self):
        from coordination.benchmark import backtest
        from coordination.config import Config
        tmp = Path(tempfile.mkdtemp())
        try:
            cfg = Config()
            cfg.benchmark.out_dir = str(tmp / "bt")
            cfg.run_root = str(tmp)
            runs = [_run(p, sc, 0, b + d) for sc, b in (("s1", 100.0), ("s2", 200.0))
                    for p, d in (("forecast_only", 0), ("heuristic", -8), ("heuristic@lam=120", -9), ("batch", -1))]
            meta = {"suite": "screening", "scenarios": ["s1", "s2"], "seeds": [0], "participation": 0.05,
                    "compliance": 1.0, "experiment_id": "x", "policies": ["forecast_only", "heuristic",
                                                                          "heuristic@lam=120", "batch"]}
            dev = {"screen": {"meta": meta, "runs": runs}}
            held = {"heldout_5": {"meta": {**meta, "experiment_id": "y"}, "runs": runs}}
            import coordination.benchmark.backtest as bt
            orig = cfg.path
            cfg.path = lambda q: tmp / q if q == "reports" else orig(q)
            (tmp / "reports").mkdir()
            sel = bt.select(dev)
            self.assertEqual((sel["best"], sel["challenger"]), ("heuristic@lam=120", "batch"))
            text = bt.final_report(cfg, "t", {}, None, held, {}).read_text(encoding="utf-8")
            self.assertIn("Partial report", text)
            self.assertNotIn("met the pre-declared", text)                  # nothing headlined without a selection
            text = bt.final_report(cfg, "t", dev, sel, held, {}).read_text(encoding="utf-8")
            self.assertIn("Other pre-declared held-out candidates", text)   # heuristic listed, not headlined
            self.assertIn("met the pre-declared development targets", text)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestGate(unittest.TestCase):
    def test_gate_sources(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            self.assertEqual(_gate(d), {})
            (d / "pipeline_manifest.json").write_text(json.dumps({"gate": {"passed": True}, "gate_overridden": False}))
            self.assertTrue(_gate(d)["passed"])
            (d / "pipeline_manifest.json").write_text(json.dumps({"gate": {"passed": False}, "gate_overridden": True}))
            self.assertFalse(_gate(d)["passed"])
            (d / "gate.json").write_text(json.dumps({"passed": True}))      # a batch's own gate wins
            self.assertTrue(_gate(d)["passed"])


class TestSweepReport(unittest.TestCase):
    def test_sweep_report_rows_and_summary(self):
        from coordination.benchmark import backtest
        from coordination.config import Config
        tmp = Path(tempfile.mkdtemp())
        try:
            cfg = Config()
            orig = cfg.path
            cfg.path = lambda q: tmp / q if q == "reports" else orig(q)
            (tmp / "reports").mkdir()
            pols = ["forecast_only", "heuristic", "batch"]
            runs = [_run(p, sc, k, b + d) for sc, b in (("s1", 100.0), ("s2", 200.0)) for k in (0, 1)
                    for p, d in (("forecast_only", 0), ("heuristic", -7), ("batch", 3))]
            meta = {"suite": "heldout", "scenarios": ["s1", "s2"], "seeds": [0, 1], "participation": 1.0,
                    "experiment_id": "h", "policies": pols}
            res = {"sweep_heldout_100": {"meta": meta, "runs": runs},
                   "sweep_dev_100": {"meta": {**meta, "experiment_id": "d"}, "runs": runs}}
            text = backtest.sweep_report(cfg, "t", [1.0], res, {}).read_text(encoding="utf-8")
            self.assertIn("Best consistent held-out reduction: `heuristic` at 100%", text)
            self.assertIn("| held-out | batch |", text.replace("1 | held-out", "| held-out"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

try:
    from tests.test_coordination_rl import HAVE, ToyMaskedEnv, greedy_accuracy, small_cfg
except ImportError:
    HAVE = False


if HAVE:
    import threading

    class LockedToy(ToyMaskedEnv):
        """Holds a lock like the real environment's coordinator: must never be pickled across processes."""
        def __init__(self, seed=0):
            super().__init__(seed)
            self.lock = threading.Lock()


@unittest.skipUnless(HAVE, "rl dependencies not installed")
class TestVectorisedDDQN(unittest.TestCase):
    def test_ppo_subprocess_envs_with_unpicklable_state(self):
        from coordination.rl.train import train_ppo
        tmp = Path(tempfile.mkdtemp())
        try:
            cfg = small_cfg(tmp)
            cfg.rl.n_envs = 2
            cfg.rl.max_decisions = 600
            s = train_ppo(cfg, 0, lambda sd: LockedToy(sd), None, "toy-net", {"toy": True}, name="ppo_vec")
            self.assertEqual(s["stopped_by"], "max_decisions")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_parallel_actors_train_and_count_every_transition(self):
        from coordination.rl import policy as pol
        from coordination.rl.train import train_ddqn
        tmp = Path(tempfile.mkdtemp())
        try:
            cfg = small_cfg(tmp)
            cfg.rl.n_envs = 2
            cfg.rl.max_decisions = 2500
            s = train_ddqn(cfg, 0, lambda sd: ToyMaskedEnv(sd), None, "toy-net", {"toy": True}, name="ddqn_vec")
            self.assertEqual(s["stopped_by"], "max_decisions")
            self.assertEqual(s["actors"], 2)
            self.assertGreaterEqual(s["decisions"], 2500)
            self.assertGreater(s["episodes"], 2500 // 8 - 4)                 # 8 decisions per toy episode
            acc = greedy_accuracy(pol.load(Path(s["run_dir"]) / "latest").act)
            self.assertGreater(acc, 0.55, f"vectorised DDQN greedy accuracy {acc:.2f}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(HAVE, "rl dependencies not installed")
class TestAsyncActorLearner(unittest.TestCase):
    """Asynchronous actors (spawned processes) + learner on the toy masked task."""

    def _run(self, algo, **kw):
        from coordination.rl import policy as pol
        from coordination.rl.async_train import train_async
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        cfg = small_cfg(tmp)
        cfg.rl.gamma = 0.0                      # the toy is a contextual bandit (independent steps)
        for k, v in kw.items():
            setattr(cfg.rl, k, v)
        s = train_async(cfg, algo, 0, lambda sd: ToyMaskedEnv(sd), lambda sd: ToyMaskedEnv(sd), "toy-net",
                        {"toy": True}, n_actors=3, rollout=256, log=None)
        self.assertEqual(s["stopped_by"], "max_decisions")
        self.assertGreater(s["param_change_l2"], 0.0)
        self.assertGreater(s["updates"], 0)
        d = Path(s["run_dir"])
        self.assertTrue((d / "latest" / "meta.json").exists())
        p = pol.load(d / "latest")
        self.assertEqual(p.algo, algo)
        return s, greedy_accuracy(p.act), d

    def test_async_ppo_learns_and_checkpoints_load(self):
        s, acc, d = self._run("appo", max_decisions=6000, ppo_lr=3e-3, batch_size=64, n_epochs=4, ent_coef=0.0)
        self.assertGreater(acc, 0.55, f"async PPO greedy accuracy {acc:.2f}")   # random ~0.3

    def test_async_ddqn_learns_and_validator_writes_best(self):
        s, acc, d = self._run("ddqn", max_decisions=4000)
        self.assertGreater(acc, 0.55, f"async DDQN greedy accuracy {acc:.2f}")
        self.assertTrue((d / "best" / "meta.json").exists())
