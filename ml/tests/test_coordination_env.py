"""RouteChoiceEnv on a tiny real SUMO network (python -m unittest tests.test_coordination_env).

Diamond: s0 -> s -> {a | b} -> t -> t1, branch b slightly longer. Background trips all enter s0->t1; participants
are revealed at their departures and routed by the policy through the shared coordinator. Uses the labeled
persistence_debug forecast (from this run's own measurements)."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from coordination.config import Config
from coordination.network import RoadNetwork

try:
    import gymnasium  # noqa: F401
    from eventsim.sumonet import sumo_bin
    HAVE = Path(sumo_bin("netconvert")).with_suffix(".exe").exists() or Path(sumo_bin("netconvert")).exists()
except Exception:
    HAVE = False

NODES = {"s0": (0, 0), "s": (200, 0), "a": (400, 150), "b": (400, -200), "t": (600, 0), "t1": (800, 0)}
ROADS = [("s0", "s"), ("s", "a"), ("a", "t"), ("s", "b"), ("b", "t"), ("t", "t1")]
BEGIN = 28800


def rid(u, v):
    return f"{u}-{v}-0"


def lonlat(x, y):
    return (-122.42 + x / 88_000.0, 37.77 + y / 110_540.0)


def build_toy(d: Path, n_bg=300, parts=((BEGIN + 3700, "p1"), (BEGIN + 3700, "p2"), (BEGIN + 3760, "p3"),
                                         (BEGIN + 3820, "p4"), (BEGIN + 3880, "p5"))):
    (d / "toy.nod.xml").write_text("<nodes>" + "".join(
        f'<node id="{k}" x="{x}" y="{y}" type="priority"/>' for k, (x, y) in NODES.items()) + "</nodes>")
    (d / "toy.edg.xml").write_text("<edges>" + "".join(
        f'<edge id="{rid(u, v)}" from="{u}" to="{v}" numLanes="1" speed="13.9"/>' for u, v in ROADS) + "</edges>")
    subprocess.run([sumo_bin("netconvert"), "-n", str(d / "toy.nod.xml"), "-e", str(d / "toy.edg.xml"), "-o",
                    str(d / "toy.net.xml"), "--no-turnarounds", "true", "--no-warnings", "true"], check=True,
                   capture_output=True)
    trips = [(f"bg{i}", BEGIN + 12.0 * i) for i in range(n_bg)] + [(pid, float(t)) for t, pid in parts]
    trips.sort(key=lambda x: x[1])
    vt = ('<vType id="car" sigma="0.5"/><vType id="probe" sigma="0.5">'
          '<param key="has.rerouting.device" value="false"/></vType>')
    (d / "trips.rou.xml").write_text("<routes>" + vt + "".join(
        f'<trip id="{i}" type="car" depart="{t:.1f}" from="{rid("s0", "s")}" to="{rid("t", "t1")}" '
        f'departLane="best" departSpeed="max"/>' for i, t in trips) + "</routes>")
    (d / "closures.add.xml").write_text("<additional/>")
    rows, geom = [], {}
    for u, v in ROADS:
        (x0, y0), (x1, y1) = NODES[u], NODES[v]
        rows.append({"road_segment_id": rid(u, v), "length_m": float(np.hypot(x1 - x0, y1 - y0)),
                     "free_flow_speed_mph": 31.1, "highway": "secondary", "lanes": 1.0})
        geom[rid(u, v)] = [list(lonlat(x0, y0)), list(lonlat(x1, y1))]
    arcs = [(rid(a, b), rid(b, c)) for a, b in ROADS for b2, c in ROADS if b2 == b]
    net = RoadNetwork.from_tables(pd.DataFrame(rows), arcs, geom, "toy-net")
    from coordination.rl.scenario import ScenarioSpec, parse_trips
    spec = ScenarioSpec(scenario_id="toy", batch="toy", family_id="toy", group="toy", split="train",
                        date="2026-09-27", time={"sim_begin_s": BEGIN, "analysis_begin_s": BEGIN,
                                                  "depart_end_s": BEGIN + 5400, "sim_end_s": BEGIN + 7200},
                        run_seed=42, net_file=d / "toy.net.xml", rou_src=d / "trips.rou.xml",
                        add_src=d / "closures.add.xml", routing={"reroute_probability": 0.0, "reroute_period_s": 300},
                        trips=parse_trips(d / "trips.rou.xml"), restrictions=[], forecast_context={})
    return net, spec


def toy_cfg(d: Path, warm=False) -> Config:
    cfg = Config()
    cfg.env.out_dir = str(d / "episodes")
    cfg.env.history_s = 3600
    cfg.env.decision_window_s = 600
    cfg.env.max_drain_s = 900
    cfg.env.participation = 1.0
    cfg.env.max_participants = 10
    cfg.env.forecast_mode = "persistence_debug"
    cfg.env.warm_state_cache = warm
    cfg.env.progress_every_s = 30
    return cfg


@unittest.skipUnless(HAVE, "SUMO / gymnasium not available")
class TestRouteChoiceEnv(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.net, cls.spec = build_toy(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def env(self, warm=False, tag="t"):
        from coordination.rl.sumo_env import RouteChoiceEnv
        return RouteChoiceEnv(toy_cfg(self.tmp, warm), self.net, [self.spec], allow_debug_forecast=True, tag=tag)

    def run_policy(self, act, warm=False, tag="t"):
        env = self.env(warm, tag)
        obs, info = env.reset(options={"seed_offset": 0})
        seen, rewards, t_at = [], [], []
        done = False
        while not done:
            t_at.append(env.t)
            seen.append(env._pending[0].id)
            a = act(obs, env.action_masks())
            obs, r, term, trunc, info = env.step(a)
            rewards.append(r)
            done = term or trunc
        applied = {}
        for v in ("p1", "p2", "p3", "p4", "p5"):
            a = env.coord.ledger.assignments.get(env.coord.ledger.by_request.get(f"toy|{v}", ""))
            a = a or env.coord.storage.by_request(f"toy|{v}")
            applied[v] = tuple(a.route) if a else None
        env.close()
        return env, info["episode_summary"], applied, rewards, seen, t_at

    def test_debug_forecast_refused_without_flag(self):
        from coordination.rl.sumo_env import RouteChoiceEnv
        env = RouteChoiceEnv(toy_cfg(self.tmp), self.net, [self.spec], allow_debug_forecast=False)
        with self.assertRaises(SystemExit):
            env.reset(options={"seed_offset": 0})
        env.close()

    def test_actions_change_routes_and_outcomes_demand_preserved(self):
        from coordination.rl.evaluate import act_alternative, act_fastest
        e1, s1, r1, rew1, seen1, _ = self.run_policy(act_fastest, tag="fast")
        e2, s2, r2, rew2, seen2, _ = self.run_policy(act_alternative, tag="alt")
        self.assertEqual(seen1, seen2)                                    # same revealed requests, same order
        self.assertGreater(s1["decisions"], 0)
        self.assertNotEqual(r1, r2)                                       # decisions changed actual paths
        via_b = lambda r: r is not None and rid("s", "b") in r
        self.assertTrue(any(via_b(r) for r in r2.values()))
        self.assertFalse(all(via_b(r) for r in r1.values()))
        for s in (s1, s2):
            self.assertEqual(s["invalid_route"], 0)
            self.assertEqual(s["route_readback_mismatch"], 0)
            self.assertEqual(s["participants"], 5)
        self.assertNotAlmostEqual(s1["in_scope_vehicle_hours"], s2["in_scope_vehicle_hours"], places=6)
        # demand preserved: every trip of the scenario appears in SUMO's tripinfo exactly once, in both runs
        import xml.etree.ElementTree as ET
        for s in (s1, s2):
            ids = [el.get("id") for el in ET.parse(Path(s["episode_dir"]) / "tripinfo.xml").getroot()]
            self.assertEqual(sorted(ids), sorted(t.id for t in self.spec.get_trips()))

    def test_reward_equals_accounted_vehicle_time(self):
        from coordination.rl.evaluate import act_fastest
        env, s, _, rewards, _, _ = self.run_policy(act_fastest, tag="rew")
        self.assertAlmostEqual(-sum(rewards) * env.cfg.env.reward_scale_s, env.acct.total_s, places=3)
        self.assertAlmostEqual(s["in_scope_vehicle_hours"] * 3600, env.acct.total_s, places=3)

    def test_same_time_requests_no_time_advance_and_ledger_updates(self):
        from coordination.rl import features as feat
        env = self.env(tag="same")
        obs1, _ = env.reset(options={"seed_offset": 0})
        t1, p1 = env.t, env._pending[0].id
        load_before = env.coord.ledger.total_load()
        obs2, *_ = env.step(0)
        self.assertEqual((p1, env._pending[0].id), ("p1", "p2"))
        self.assertEqual(env.t, t1)                                       # same departure: no simulated time passed
        self.assertGreater(env.coord.ledger.total_load(), load_before)    # first choice already in the ledger
        F = len(feat.CAND_FEATURES)
        self.assertGreater(obs2[F * 0 + feat.CAND_FEATURES.index("load_ratio_mean")],
                           obs1[F * 0 + feat.CAND_FEATURES.index("load_ratio_mean")])
        self.assertAlmostEqual(env.coord.clock(), self.spec.utc(env.t))  # ledger/expiry run on simulated time
        env.close()

    def test_invalid_action_rejected_without_side_effects(self):
        from coordination.rl.sumo_env import InvalidAction
        env = self.env(tag="inv")
        env.reset(options={"seed_offset": 0})
        mask = env.action_masks()
        bad = int(np.flatnonzero(~mask)[0])
        q, t, v = len(env.queue), env.t, env.coord.ledger.version
        with self.assertRaises(InvalidAction):
            env.step(bad)
        self.assertEqual((len(env.queue), env.t, env.coord.ledger.version), (q, t, v))
        env.close()

    def test_forecast_refreshes_from_own_history(self):
        from coordination.rl.evaluate import act_fastest
        env, s, *_ = self.run_policy(act_fastest, tag="fc")
        self.assertGreaterEqual(s["forecast_refreshes"], 2)               # at the first decision + every 10 min
        self.assertEqual(s["forecast_refresh_failures"], 0)
        self.assertGreaterEqual(len(env.meas.history), 6)
        self.assertEqual(env.bridge.refreshes, s["forecast_refreshes"])

    def test_warm_state_reuse_is_verified_and_matches(self):
        from coordination.rl.evaluate import act_fastest
        _, s_cold, r_cold, rew_cold, *_ = self.run_policy(act_fastest, warm=True, tag="cold")
        _, s_warm, r_warm, rew_warm, *_ = self.run_policy(act_fastest, warm=True, tag="warm")
        self.assertFalse(s_cold["used_warm_state"])
        self.assertTrue(s_warm["used_warm_state"])
        self.assertEqual(r_cold, r_warm)

    def test_benchmark_episode_identity_repeatability_and_congestion(self):
        """Backtest episodes (runner.BenchEnv): matched population digests across policies, exact repeatability of
        a fixed policy from a verified warm state, and congestion exposure consistent with the accountant."""
        from coordination.benchmark import runner
        cfg = toy_cfg(self.tmp / "bench", warm=True)          # own cache: other tests expect a cold start
        env_cls = runner._env_cls()

        def episode(policy, tag):
            c, _, window = runner.policy_setup(cfg, policy)
            env = env_cls(c, self.net, [self.spec], policy_name=policy, tag=tag, allow_debug_forecast=True)
            try:
                return env.run_policy("toy", 0, runner.chooser(c, policy), window)
            finally:
                env.close()

        episode("forecast_only", "bw")                                    # builds the shared warm state
        a = episode("forecast_only", "b1")
        b = episode("forecast_only@rep=1", "b2")
        h = episode("heuristic@w=60", "b3")
        for s in (a, b, h):
            self.assertTrue(s["used_warm_state"])
            self.assertTrue(runner.quality(s)["complete"], runner.quality(s))
            self.assertEqual(s["identity"], a["identity"])               # same demand, cohort, draws, start state
        self.assertEqual(a["in_scope_vehicle_hours"], b["in_scope_vehicle_hours"])   # repeatable
        self.assertEqual(a["congestion"], b["congestion"])
        c = a["congestion"]
        self.assertGreater(c["observed_h_scope"], 0)
        self.assertLessEqual(c["congested_h_scope"], c["observed_h_scope"])
        self.assertLessEqual(c["observed_h_scope"] + c["pending_h_scope"], a["in_scope_vehicle_hours"] + 1e-9)
        self.assertGreater(h["bench"]["batch_delay_s_mean"], 0)          # equal-timing control really waited
        self.assertTrue((Path(a["episode_dir"]) / "congestion_series.json").exists())
        from coordination.rl.sumo_env import sumo_backend
        self.assertEqual(a["sumo_backend"], sumo_backend("traci"))      # TP_SUMO_BACKEND=libsumo on cloud nodes

    def test_keep_outputs_with_and_without_warm_state(self):
        """Full outputs (vehicle routes, 5-min edge data) do not change a warm-loaded episode, and work after loading
        a state built with or without them. (Under libsumo a cold continuation and a warm load can differ slightly;
        every compared episode therefore loads the same saved state.)"""
        import gzip
        from coordination.benchmark import runner
        env_cls = runner._env_cls()

        def episode(keep, tag, d):
            cfg = toy_cfg(self.tmp / d, warm=True)
            cfg.env.keep_outputs = keep
            env = env_cls(cfg, self.net, [self.spec], policy_name="forecast_only", tag=tag, allow_debug_forecast=True)
            try:
                return env.run_policy("toy", 0, runner.chooser(cfg, "forecast_only"), 0.0)
            finally:
                env.close()

        episode(False, "p0", "ko")                                          # builds a warm state without outputs
        plain = episode(False, "p1", "ko")                                  # warm-loaded, no outputs
        kept = episode(True, "k1", "ko")                                    # warm-loaded, with outputs
        episode(True, "k2", "ko_cold")                                      # builds a state with outputs
        again = episode(True, "k3", "ko_cold")                              # loads a state built with outputs
        self.assertTrue(plain["used_warm_state"] and kept["used_warm_state"] and again["used_warm_state"])
        self.assertEqual(plain["in_scope_vehicle_hours"], kept["in_scope_vehicle_hours"])
        self.assertEqual(plain["congestion"], kept["congestion"])
        for s in (kept, again):
            d = Path(s["episode_dir"])
            with gzip.open(d / "vehroutes.xml.gz", "rt") as f:
                self.assertIn("<vehicle", f.read())
            with gzip.open(d / "edgedata.xml.gz", "rt") as f:
                self.assertIn("<interval", f.read())

if __name__ == "__main__":
    unittest.main()
