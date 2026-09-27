"""Unit tests for leakage-sensitive and geometry helpers. Run: python -m unittest discover -s tests -t ."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

import numpy as np

from eventsim.dataset import assign_splits
from eventsim.features import (FEATURES, MAX_TT, ObsModel, build_features, declared_estimate, event_rule, persistence,
                               true_travel_time)
from eventsim.geo import LocalProj, point_polyline_dist, polyline_length, sample_polyline
from eventsim.osm import norm_street, parse_lanes, parse_mph
from eventsim.prepare import largest_scc

OBS = {"speed_noise_sigma": 0.1, "tomtom_missing": 0.2, "stale_prob": 0.1,
       "event_estimate_sigma": 0.3, "event_estimate_missing": 0.2}


def fake_static(n=6):
    rng = np.random.default_rng(0)
    length = rng.uniform(50, 200, n)
    ff = np.full(n, 11.0)
    up = np.zeros((n, n), np.float32)
    down = np.zeros((n, n), np.float32)
    for i in range(n - 1):
        down[i, i + 1] = 1
        up[i + 1, i] = 1
    return SimpleNamespace(
        n=n, length=length, ff_speed=ff, ff_tt=length / ff, lanes=np.ones(n), rank=np.ones(n), oneway=np.zeros(n),
        signal=np.zeros(n), tomtom=np.array([True, True, False, True, False, True])[:n], dist=np.linspace(0, 1200, n),
        heading_cos=np.zeros(n), deg_in=up.sum(1), deg_out=down.sum(1), up_m=up, down_m=down,
        near300=np.eye(n, dtype=np.float32), area=np.linspace(0, 1200, n) <= 300, in_sim=np.ones(n, bool))


class FeatureCausality(unittest.TestCase):
    def _features(self, speeds, t):
        st = fake_static()
        T = speeds.shape[0]
        obs = ObsModel(st, OBS, seed=1, n_buckets=T)
        measured = np.ones(st.n, bool)
        for b in range(T):
            obs.observe(b, speeds[b], measured)
        base = persistence(st, obs, t)
        closed = np.zeros((T, st.n), bool)
        return build_features(st, obs, t, 3, sim_begin_s=36000, closed=closed, declared=(39600, 64800),
                              event_estimate=500.0, base=base), base[0]

    def test_future_observations_do_not_change_features(self):
        rng = np.random.default_rng(3)
        sp = rng.uniform(2, 12, (12, 6))
        f1, b1 = self._features(sp, 5)
        sp2 = sp.copy()
        sp2[6:] = 0.1  # the future turns into gridlock
        f2, b2 = self._features(sp2, 5)
        np.testing.assert_array_equal(np.nan_to_num(f1, nan=-9), np.nan_to_num(f2, nan=-9))
        np.testing.assert_array_equal(b1, b2)
        self.assertEqual(f1.shape[1], len(FEATURES))

    def test_observations_in_order(self):
        st = fake_static()
        obs = ObsModel(st, OBS, seed=1, n_buckets=4)
        with self.assertRaises(AssertionError):
            obs.observe(1, np.ones(st.n), np.ones(st.n, bool))


class Targets(unittest.TestCase):
    def test_empty_bucket_is_not_a_measurement(self):
        tt, ok = true_travel_time(np.array([[np.nan, 10.0, 0.0]]), np.array([[0.0, 50.0, 50.0]]), np.array([100.0] * 3))
        self.assertTrue(np.isnan(tt[0, 0]))
        self.assertFalse(ok[0, 0])
        self.assertAlmostEqual(tt[0, 1], 10.0)
        self.assertLessEqual(tt[0, 2], MAX_TT)  # stopped: floored speed, capped time

    def test_event_rule_only_near_declared_event(self):
        st = fake_static()
        base = st.ff_tt.copy()
        np.testing.assert_array_equal(event_rule(st, base, 40000, None), base)
        out = event_rule(st, base, 64800, (39600, 64800))  # at declared end -> departure window
        self.assertGreater(out[0], base[0])
        self.assertEqual(out[-1], base[-1])  # 1200 m away: unchanged


class Splits(unittest.TestCase):
    def test_families_stay_whole_and_hard_goes_to_test(self):
        fams = {f"f{i:03d}": {"hard_test": i in (2, 9)} for i in range(20)}
        ctx = SimpleNamespace(fams=fams)
        s = assign_splits(ctx)
        self.assertEqual(set(s), set(fams))
        self.assertEqual(s["f002"], "test")
        self.assertEqual(s["f009"], "test")
        self.assertTrue({"train", "val", "test"} <= set(s.values()))
        self.assertEqual(s, assign_splits(ctx))  # reproducible

    def test_declared_estimate(self):
        fam = {"event": {"vehicle_trips": 1000, "turnout_factor": 1.0}, "observation": OBS}
        self.assertEqual(declared_estimate(fam, False, np.random.default_rng(0)), 0.0)
        vals = [declared_estimate(fam, True, np.random.default_rng(i)) for i in range(200)]
        self.assertTrue(any(np.isnan(v) for v in vals))
        finite = [v for v in vals if not np.isnan(v)]
        self.assertTrue(all(v != 1000 for v in finite))  # never the exact generated count


class Geometry(unittest.TestCase):
    def test_sampling_and_distance(self):
        xy = np.array([[0.0, 0.0], [100.0, 0.0]])
        pts, dirs = sample_polyline(xy, 10.0)
        self.assertEqual(len(pts), 11)
        np.testing.assert_allclose(dirs, [[1, 0]] * 11)
        d, _ = point_polyline_dist(np.array([[50.0, 5.0]]), xy)
        self.assertAlmostEqual(d[0], 5.0)
        self.assertAlmostEqual(polyline_length(xy), 100.0)

    def test_projection_roundtrip(self):
        p = LocalProj(-122.43, 37.76)
        ll = np.array([[-122.431, 37.761]])
        np.testing.assert_allclose(p.inv(p.fwd(ll)), ll, atol=1e-9)

    def test_street_names(self):
        self.assertEqual(norm_street("17th Street"), norm_street("17TH ST"))
        self.assertEqual(norm_street("Market Street"), "MARKET")
        self.assertNotEqual(norm_street("Noe Street"), norm_street("Market Street"))
        self.assertEqual(parse_mph("['25 mph', '30 mph']"), 30)
        self.assertEqual(parse_lanes("['2', '3']"), 3)

    def test_largest_scc(self):
        arcs = [("a", "b"), ("b", "c"), ("c", "a"), ("c", "d"), ("d", "e")]
        self.assertEqual(largest_scc(arcs), {"a", "b", "c"})


if __name__ == "__main__":
    unittest.main()
