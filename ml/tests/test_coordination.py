"""Coordinated routing POC tests (python -m unittest tests.test_coordination). Tiny synthetic networks; one smoke test
on the real net_v3 network runs only if its artifacts and the fixture exist."""
from __future__ import annotations

import itertools
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from coordination import timing
from coordination.candidates import generate
from coordination.config import Config
from coordination.coordinator import Conflict, Coordinator
from coordination.forecast_store import ForecastInvalid, ForecastStore, validate
from coordination.network import RoadNetwork
from coordination.schemas import Candidate, RequestCandidates, RouteRequest, SelectionContext, TimedRoute
from coordination.selectors import Batch, ForecastOnly, Heuristic
from coordination.selectors.base import exact_joint_score
from coordination.storage import Storage

ISSUED = pd.Timestamp("2026-09-27T17:30:00Z")
T0 = ISSUED.timestamp()
NETV = "test-net"


def rid(u, v):
    return f"{u}-{v}-0"


def make_net(nodes: dict, roads: list, arcs=None, no_uturn=True, alias: dict | None = None, hw="residential",
             lanes=1.0) -> RoadNetwork:
    """nodes: name -> (lon, lat); roads: [(u, v)] one-way directed; arcs default: every legal continuation."""
    rows, geom = [], {}
    for u, v in roads:
        (x0, y0), (x1, y1) = nodes[u], nodes[v]
        L = math.hypot((x1 - x0) * 111_320 * math.cos(math.radians(37.77)), (y1 - y0) * 110_540)
        rows.append({"road_segment_id": rid(u, v), "length_m": L, "free_flow_speed_mph": 25.0, "highway": hw,
                     "lanes": lanes, "represented_by": (alias or {}).get(rid(u, v))})
        geom[rid(u, v)] = [list(nodes[u]), list(nodes[v])]
    if arcs is None:
        arcs = [(rid(u, v), rid(v, w)) for (u, v) in roads for (v2, w) in roads if v2 == v and not (no_uturn and w == u)]
    return RoadNetwork.from_tables(pd.DataFrame(rows), arcs, geom, NETV)


def grid(n=3, d=0.002):
    nodes = {f"n{i}{j}": (-122.42 + d * i, 37.77 + d * j) for i in range(n) for j in range(n)}
    roads = []
    for i in range(n):
        for j in range(n):
            for di, dj in ((1, 0), (0, 1)):
                if i + di < n and j + dj < n:
                    a, b = f"n{i}{j}", f"n{i + di}{j + dj}"
                    roads += [(a, b), (b, a)]
    return nodes, roads


def diamond():
    """origin road s0->s, two branches (s-a-t fast, s-b-t slower), destination road t->t1."""
    nodes = {"s0": (-122.420, 37.770), "s": (-122.418, 37.770), "a": (-122.416, 37.7715), "b": (-122.416, 37.7685),
             "t": (-122.414, 37.770), "t1": (-122.412, 37.770)}
    roads = [("s0", "s"), ("s", "a"), ("a", "t"), ("s", "b"), ("b", "t"), ("t", "t1")]
    return nodes, roads


def forecast_df(net: RoadNetwork, factor=None, per_bucket=None, availability=None, H=6, issued=ISSUED,
                network_version=NETV) -> pd.DataFrame:
    rows = []
    for k in range(H):
        for i, s in enumerate(net.ids):
            f = (factor or {}).get(s, 1.0) * ((per_bucket or {}).get((s, k), 1.0))
            av = (availability or {}).get((s, k), "open")
            usable = av == "open"
            rep = net.ids[net.resource[i]] if net.resource[i] != i else None
            rows.append({"road_segment_id": s, "issued_at": issued,
                         "valid_from": issued + pd.Timedelta(minutes=10 * k),
                         "valid_to": issued + pd.Timedelta(minutes=10 * (k + 1)), "horizon_min": 10 * (k + 1),
                         "predicted_travel_time_sec": net.ff_tt_s[i] * f if usable else np.nan,
                         "predicted_speed_mph": 25.0 / f if usable else np.nan,
                         "predicted_congestion_ratio": 1 - 1 / f if usable else np.nan,
                         "availability": av, "restriction_reason": "none" if usable else "scheduled_closure",
                         "prediction_source": ("representative_road" if rep else "model") if usable else "none",
                         "represented_by": rep, "model_version": "test-model", "network_version": network_version,
                         "dataset_id": "test", "training_source": "test", "input_source": "test",
                         "synthetic_training": True})
    return pd.DataFrame(rows)


def closures_df(items):
    return pd.DataFrame([{"road_segment_id": r, "case_num": "c", "kind": "permit", "restriction": kind,
                          "closure_begin": pd.Timestamp(b, unit="s", tz="UTC"),
                          "closure_end": pd.Timestamp(e, unit="s", tz="UTC")} for r, b, e, kind in items],
                        columns=["road_segment_id", "case_num", "kind", "restriction", "closure_begin", "closure_end"])


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def mid(nodes, u, v, f=0.5):
    (x0, y0), (x1, y1) = nodes[u], nodes[v]
    return (x0 + (x1 - x0) * f, y0 + (y1 - y0) * f)


def coord(net, snap, cfg=None, db=":memory:", now=T0 + 60, selector="heuristic"):
    cfg = cfg or Config()
    store = ForecastStore(net, 10, 6, cfg.forecast.max_issue_age_min)
    store.publish(snap)
    return Coordinator(cfg, net, store, Storage(db), clock=Clock(now), selector=selector)


class TestNetworkAndTiming(unittest.TestCase):
    def setUp(self):
        self.nodes, roads = grid()
        self.net = make_net(self.nodes, roads)
        self.snap = validate(forecast_df(self.net), None, self.net)

    def test_legal_turns_respected(self):
        a, b = self.net.pos[rid("n00", "n10")], self.net.pos[rid("n10", "n20")]
        arcs = [(self.net.ids[x], self.net.ids[y]) for x, y in zip(self.net.src, self.net.dst) if not (x == a and y == b)]
        nodes, roads = grid()
        net2 = RoadNetwork.from_tables(pd.DataFrame({
            "road_segment_id": self.net.ids, "length_m": self.net.length_m, "free_flow_speed_mph": 25.0,
            "highway": "residential", "lanes": 1.0}), arcs, {s: g.tolist() for s, g in zip(self.net.ids, self.net.geometry)}, NETV)
        snap2 = validate(forecast_df(net2), None, net2)
        with self.assertRaises(timing.Infeasible) as e:
            timing.evaluate(net2, snap2, [a, b], 0.0, 1.0, T0)
        self.assertEqual(e.exception.reason, "illegal_connection")
        o = net2.snap(mid(nodes, "n00", "n10", 0.5), max_m=5)
        d = net2.snap(mid(nodes, "n10", "n20", 0.5), max_m=5)
        cs = generate(net2, snap2, [s for s in o if net2.ids[s.road] == rid("n00", "n10")],
                      [s for s in d if net2.ids[s.road] == rid("n10", "n20")], T0, Config().candidates)
        self.assertTrue(cs.candidates)
        for c in cs.candidates:
            for x, y in zip(c.road_ids, c.road_ids[1:]):
                self.assertTrue(net2.has_arc(net2.pos[x], net2.pos[y]))
                self.assertFalse((x, y) == (rid("n00", "n10"), rid("n10", "n20")))

    def test_interval_boundary_uses_entry_bucket(self):
        r = rid("n00", "n10")
        i = self.net.pos[r]
        snap = validate(forecast_df(self.net, per_bucket={(r, 1): 3.0}), None, self.net)
        tr0 = timing.evaluate(self.net, snap, [i], 0.0, 1.0, T0 + 599.999)
        tr1 = timing.evaluate(self.net, snap, [i], 0.0, 1.0, T0 + 600.0)
        self.assertAlmostEqual(tr0.eta_s, self.net.ff_tt_s[i], places=4)
        self.assertAlmostEqual(tr1.eta_s, 3 * self.net.ff_tt_s[i], places=4)

    def test_full_closure_requires_clearance_and_entry_only_after_end(self):
        a, b = self.net.pos[rid("n00", "n10")], self.net.pos[rid("n10", "n20")]
        tta = self.net.ff_tt_s[a]
        # closure on b starts while the vehicle would still be on b -> refused
        snap = validate(forecast_df(self.net), closures_df([(rid("n10", "n20"), T0 + tta + 5, T0 + 3000, "full")]),
                        self.net)
        with self.assertRaises(timing.Infeasible) as e:
            timing.evaluate(self.net, snap, [a, b], 0.0, 1.0, T0)
        self.assertEqual(e.exception.reason, "closure")
        # closure ended before entry -> fine
        snap = validate(forecast_df(self.net), closures_df([(rid("n10", "n20"), T0 - 100, T0 + tta - 1, "full")]), self.net)
        timing.evaluate(self.net, snap, [a, b], 0.0, 1.0, T0)

    def test_origin_on_closed_road_can_leave(self):
        a, b = self.net.pos[rid("n00", "n10")], self.net.pos[rid("n10", "n20")]
        snap = validate(forecast_df(self.net, availability={(rid("n00", "n10"), 0): "closed"}),
                        closures_df([(rid("n00", "n10"), T0 - 100, T0 + 3000, "full")]), self.net)
        tr = timing.evaluate(self.net, snap, [a, b], 0.3, 1.0, T0)
        self.assertIn("origin_cost_free_flow", tr.flags)
        with self.assertRaises(timing.Infeasible):     # but nobody may ENTER it
            timing.evaluate(self.net, snap, [self.net.pos[rid("n10", "n00")], a], 0.0, 1.0, T0)

    def test_missing_forecast_is_not_free_flow(self):
        df = forecast_df(self.net)
        df = df[~((df.road_segment_id == rid("n10", "n20")) & (df.horizon_min == 10))]
        snap = validate(df, None, self.net)
        with self.assertRaises(timing.Infeasible) as e:
            timing.evaluate(self.net, snap, [self.net.pos[rid("n00", "n10")], self.net.pos[rid("n10", "n20")]], 0, 1, T0)
        self.assertEqual(e.exception.reason, "not_enterable")

    def test_beyond_horizon_refused(self):
        with self.assertRaises(timing.Infeasible) as e:
            timing.evaluate(self.net, self.snap, [self.net.pos[rid("n00", "n10")], self.net.pos[rid("n10", "n20")]],
                            0, 1, T0 + 3600 - 5)
        self.assertEqual(e.exception.reason, "beyond_horizon")

    def test_partial_edge_snapping_and_pricing(self):
        r = rid("n00", "n10")
        s = [x for x in self.net.snap(mid(self.nodes, "n00", "n10", 0.25), max_m=5) if self.net.ids[x.road] == r][0]
        self.assertAlmostEqual(s.fraction, 0.25, places=3)
        self.assertLess(s.distance_m, 0.5)
        self.assertEqual(self.net.snap((-122.0, 37.0)), [])            # far away -> unsupported
        i = self.net.pos[r]
        tr = timing.evaluate(self.net, self.snap, [i, self.net.pos[rid("n10", "n20")]], 0.25, 0.5, T0)
        self.assertAlmostEqual(tr.eta_s, 0.75 * self.net.ff_tt_s[i] + 0.5 * self.net.ff_tt_s[self.net.pos[rid("n10", "n20")]])

    def test_same_road_trip(self):
        r = rid("n00", "n10")
        o = [x for x in self.net.snap(mid(self.nodes, "n00", "n10", 0.2), max_m=5) if self.net.ids[x.road] == r]
        d = [x for x in self.net.snap(mid(self.nodes, "n00", "n10", 0.8), max_m=5) if self.net.ids[x.road] == r]
        cs = generate(self.net, self.snap, o, d, T0, Config().candidates)
        self.assertEqual(cs.candidates[0].road_ids, [r])
        self.assertAlmostEqual(cs.candidates[0].eta_s, 0.6 * self.net.ff_tt_s[self.net.pos[r]], places=4)

    def test_alias_shares_allocation_resource(self):
        nodes = {"a": (-122.42, 37.77), "b": (-122.418, 37.77), "a2": (-122.42, 37.7701), "b2": (-122.418, 37.7701)}
        net = make_net(nodes, [("a", "b"), ("a2", "b2")], arcs=[], alias={rid("a2", "b2"): rid("a", "b")})
        self.assertEqual(net.resource[net.pos[rid("a2", "b2")]], net.pos[rid("a", "b")])
        from coordination.schemas import RoadEntry
        cells = timing.cells(net, [RoadEntry(net.pos[rid("a", "b")], T0, T0 + 1),
                                   RoadEntry(net.pos[rid("a2", "b2")], T0, T0 + 1)], 300, [1.0])
        self.assertEqual(cells, {(net.pos[rid("a", "b")], int(T0 // 300)): 2.0})

    def test_spread_conserves_weight(self):
        from coordination.schemas import RoadEntry
        cells = timing.cells(self.net, [RoadEntry(0, T0, T0 + 1)], 300, [1, 2, 1])
        self.assertAlmostEqual(sum(cells.values()), 1.0)
        self.assertEqual(len(cells), 3)


class TestForecastStore(unittest.TestCase):
    def setUp(self):
        nodes, roads = grid()
        self.net = make_net(nodes, roads)

    def test_rejects_malformed(self):
        good = forecast_df(self.net)
        bad = [pd.concat([good, good.iloc[:1]]),                                          # duplicate key
               good.assign(predicted_travel_time_sec=np.where(good.index == 0, -1.0, good.predicted_travel_time_sec)),
               good.assign(network_version="other"),
               good[good.horizon_min != 30],                                              # gap in horizons
               good.assign(valid_from=good.valid_from + pd.Timedelta(minutes=1))]         # not contiguous
        for b in bad:
            with self.assertRaises(ForecastInvalid):
                validate(b, None, self.net)

    def test_last_good_snapshot_kept_and_refresh_atomic(self):
        c = coord(self.net, validate(forecast_df(self.net), None, self.net))
        v0 = c.store.current.version
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bad.parquet"
            forecast_df(self.net).assign(network_version="other").to_parquet(p)
            r = c.refresh_forecast(p)
            self.assertFalse(r["published"])
            self.assertEqual(c.store.current.version, v0)
            p2 = Path(d) / "good.parquet"
            forecast_df(self.net, factor={rid("n00", "n10"): 1.5}, issued=ISSUED + pd.Timedelta(minutes=10)).to_parquet(p2)
            r = c.refresh_forecast(p2)
            self.assertTrue(r["published"])
            self.assertNotEqual(c.store.current.version, v0)

    def test_stale_forecast_unsupported(self):
        nodes, _ = grid()
        c = coord(self.net, validate(forecast_df(self.net), None, self.net), now=T0 + 21 * 60)
        r = c.recommend(RouteRequest("r", mid(nodes, "n00", "n10"), mid(nodes, "n12", "n22"), T0 + 21 * 60))
        self.assertEqual((r["outcome"], r["reason"]), ("unsupported", "forecast_stale"))


class TestLedgerLifecycle(unittest.TestCase):
    def setUp(self):
        self.nodes, roads = grid()
        self.net = make_net(self.nodes, roads)
        self.snap = validate(forecast_df(self.net), None, self.net)
        self.c = coord(self.net, self.snap)
        self.o, self.d = mid(self.nodes, "n00", "n10", 0.3), mid(self.nodes, "n21", "n22", 0.6)

    def req(self, rid_="r1", reserve=True):
        return RouteRequest(rid_, self.o, self.d, self.c.clock(), reserve=reserve)

    def test_preview_allocates_nothing(self):
        r = self.c.recommend(self.req(reserve=False))
        self.assertEqual(r["outcome"], "preview")
        self.assertEqual(self.c.ledger.total_load(), 0)

    def test_recommend_reserves_one_route_and_duplicate_is_idempotent(self):
        r = self.c.recommend(self.req())
        self.assertEqual(r["outcome"], "recommendation")
        n_entries = len(r["recommended"]["road_segment_ids"])
        self.assertAlmostEqual(self.c.ledger.total_load(), n_entries)       # alternatives reserve nothing
        r2 = self.c.recommend(self.req())
        self.assertTrue(r2["duplicate"])
        self.assertEqual(r2["assignment"]["assignment_id"], r["assignment"]["assignment_id"])
        self.assertAlmostEqual(self.c.ledger.total_load(), n_entries)

    def test_expiry_and_cancel_release(self):
        r = self.c.recommend(self.req())
        self.c.clock.t += 61
        self.c.sweep()
        self.assertEqual(self.c.ledger.total_load(), 0)
        self.assertEqual(self.c.get(r["assignment"]["assignment_id"])["assignment"]["status"], "expired")
        r = self.c.recommend(self.req("r2"))
        a = r["assignment"]
        self.c.cancel(a["assignment_id"], a["version"])
        self.assertEqual(self.c.ledger.total_load(), 0)

    def test_version_conflict(self):
        a = self.c.recommend(self.req())["assignment"]
        with self.assertRaises(Conflict):
            self.c.accept(a["assignment_id"], a["version"] + 5)

    def test_alternate_acceptance_revalidates(self):
        r = self.c.recommend(self.req())
        self.assertTrue(r["alternatives"])
        alt = r["alternatives"][0]
        a = r["assignment"]
        with self.assertRaises(Conflict):
            self.c.accept(a["assignment_id"], a["version"], "not-a-displayed-candidate")
        acc = self.c.accept(a["assignment_id"], a["version"], alt["candidate_id"])
        self.assertEqual(acc["assignment"]["status"], "accepted")
        self.assertEqual(acc["route"]["candidate_id"], alt["candidate_id"])
        self.assertAlmostEqual(self.c.ledger.total_load(), len(alt["road_segment_ids"]))
        dup = self.c.accept(a["assignment_id"], a["version"], alt["candidate_id"])
        self.assertTrue(dup["duplicate"])

    def test_progress_removes_passed_entries_and_reroute_replaces_atomically(self):
        r = self.c.recommend(self.req())
        a = r["assignment"]
        acc = self.c.accept(a["assignment_id"], a["version"])
        route = acc["route"]["road_segment_ids"]
        self.assertGreaterEqual(len(route), 3)
        self.c.clock.t += 30
        p = self.c.progress(a["assignment_id"], acc["assignment"]["version"], route[2])
        self.assertEqual(p["assignment"]["status"], "active")
        self.assertAlmostEqual(self.c.ledger.total_load(), len(route) - 2)
        dup = self.c.progress(a["assignment_id"], acc["assignment"]["version"], route[2])
        self.assertTrue(dup["duplicate"])
        self.assertAlmostEqual(self.c.ledger.total_load(), len(route) - 2)
        with self.assertRaises(Conflict):
            self.c.progress(a["assignment_id"], p["assignment"]["version"], "no-such-road")
        rr = self.c.reroute(a["assignment_id"], p["assignment"]["version"], route[2])
        self.assertAlmostEqual(self.c.ledger.total_load(), len(rr["route"]["road_segment_ids"]))
        self.c.complete(a["assignment_id"], rr["assignment"]["version"])
        self.assertEqual(self.c.ledger.total_load(), 0)

    def test_restart_recovery(self):
        with tempfile.TemporaryDirectory() as d:
            db = str(Path(d) / "ledger.sqlite")
            c1 = coord(self.net, self.snap, db=db)
            r = c1.recommend(RouteRequest("x", self.o, self.d, c1.clock()))
            c1.accept(r["assignment"]["assignment_id"], 1)
            load = dict(c1.ledger.load)
            c1.storage.close()
            c2 = coord(self.net, self.snap, db=db)
            self.assertEqual(c2.recovered, 1)
            self.assertEqual(dict(c2.ledger.load), load)
            self.assertTrue(c2.recommend(RouteRequest("x", self.o, self.d, c2.clock()))["duplicate"])
            c2.storage.close()

    def test_failed_persistence_returns_no_commitment(self):
        class Broken(Storage):
            def save_many(self, assigns):
                raise OSError("disk full")
        store = self.c.store
        c = Coordinator(Config(), self.net, store, Broken(":memory:"), clock=Clock(T0 + 60))
        r = c.recommend(RouteRequest("y", self.o, self.d, c.clock()))
        self.assertEqual(r["outcome"], "error")
        self.assertEqual(c.ledger.total_load(), 0)

    def test_rl_unavailable_falls_back_explicitly(self):
        r = self.c.recommend(self.req(), selector="rl")
        self.assertEqual(r["selector"]["name"], "heuristic")
        self.assertIn("rl_not_trained", r["selector"]["fallback_reason"])


class TestSelectors(unittest.TestCase):
    def setUp(self):
        self.nodes, roads = diamond()
        self.net = make_net(self.nodes, roads, hw="residential")
        slow = {rid("s", "b"): 1.08, rid("b", "t"): 1.08}
        self.snap = validate(forecast_df(self.net, factor=slow), None, self.net)
        self.cfg = Config()
        self.cfg.score.budget_per_lane = {"residential": 1.0, "minor": 1.0}
        self.o, self.d = mid(self.nodes, "s0", "s", 0.5), mid(self.nodes, "t", "t1", 0.5)

    def run_many(self, selector, n=6, lam=None, same_time=True):
        cfg = self.cfg
        if lam is not None:
            cfg = Config()
            cfg.score.budget_per_lane = self.cfg.score.budget_per_lane
            cfg.score.lam = lam
        c = coord(self.net, self.snap, cfg=cfg, selector=selector)
        out = []
        for i in range(n):
            if not same_time:
                c.clock.t = T0 + 60 + i * 400      # different 5-min bins, forecast stays fresh
            out.append(c.recommend(RouteRequest(f"u{i}", self.o, self.d, c.clock())))
        return c, out

    def test_two_candidates_detour_bound(self):
        c, out = self.run_many("forecast_only", n=1)
        r = out[0]
        self.assertEqual(len(r["alternatives"]), 1)
        self.assertLessEqual(r["alternatives"][0]["extra_travel_sec"],
                             min(180, 0.15 * r["fastest_candidate"]["forecast_eta_sec"]))

    def test_forecast_only_ignores_load_heuristic_spreads(self):
        _, fo = self.run_many("forecast_only")
        self.assertTrue(all(r["is_fastest"] for r in fo))
        _, he = self.run_many("heuristic")
        self.assertTrue(any(not r["is_fastest"] for r in he))
        for r in he:   # ETA reported is forecast ETA, never the selection score
            ch = r["allocation_diagnostics"]["selection_scores"][r["recommended"]["candidate_id"]]
            self.assertAlmostEqual(ch["eta_s"], r["recommended"]["forecast_eta_sec"], places=0)
            self.assertIn("lower_concentration_within_detour_bound" if not r["is_fastest"] else "fastest_candidate",
                          r["reasons"])

    def test_lambda_zero_equals_forecast_only(self):
        _, fo = self.run_many("forecast_only")
        _, h0 = self.run_many("heuristic", lam=0.0)
        self.assertEqual([r["recommended"]["candidate_id"] for r in fo], [r["recommended"]["candidate_id"] for r in h0])

    def test_different_times_do_not_interact(self):
        _, out = self.run_many("heuristic", n=3, same_time=False)
        self.assertEqual([r["outcome"] for r in out], ["recommendation"] * 3)
        self.assertTrue(all(r["is_fastest"] for r in out))

    def test_no_alternative(self):
        nodes = {"a": (-122.42, 37.77), "b": (-122.418, 37.77), "c": (-122.416, 37.77)}
        net = make_net(nodes, [("a", "b"), ("b", "c")])
        c = coord(net, validate(forecast_df(net), None, net))
        r = c.recommend(RouteRequest("r", mid(nodes, "a", "b"), mid(nodes, "b", "c"), c.clock()))
        self.assertEqual(r["outcome"], "recommendation")
        self.assertEqual(r["alternatives"], [])
        self.assertTrue(r["is_fastest"])

    def test_batch_selector_runs_in_coordinator(self):
        c = coord(self.net, self.snap, cfg=self.cfg, selector="batch")
        res = c.recommend_batch([RouteRequest(f"b{i}", self.o, self.d, c.clock()) for i in range(6)])
        self.assertTrue(all(r["outcome"] == "recommendation" for r in res))
        self.assertTrue(any(not r["is_fastest"] for r in res))
        self.assertIsNone(res[0]["selector"]["fallback_reason"])


def toy_context(seed=0, lam=50.0, spread=False):
    """3 requests x 3 candidates with hand-made cells on 4 shared resources."""
    rng = np.random.default_rng(seed)
    items = []
    for i in range(3):
        cands = []
        for k in range(3):
            eta = 300 + 10 * k + rng.uniform(0, 5)
            cells = {}
            for r in rng.choice(4, size=2, replace=False):
                if spread:
                    cells[(int(r), 0)] = 0.5
                    cells[(int(r), 1)] = 0.5
                else:
                    cells[(int(r), 0)] = 1.0
            tr = TimedRoute(roads=[], entries=[], depart=0, arrive=eta, distance_m=0)
            cands.append(Candidate(candidate_id=f"c{i}{k}", road_ids=[], timed=tr, origin_fraction=0,
                                   dest_fraction=1, cells=cells))
        items.append(RequestCandidates(RouteRequest(f"r{i}", (0, 0), (0, 0), 0), cands, [True] * 3, cands[0].eta_s))
    base = {(0, 0): 1.0, (2, 1): 0.5}
    return SelectionContext(items=items, base_load=lambda c: base.get(c, 0.0), cell_coef=lambda c: 1.0 + 0.5 * c[0],
                            lam=lam, forecast_version="t", ledger_version=0, deadline_ms=250, seed=seed)


class TestBatchSolver(unittest.TestCase):
    def exhaustive(self, ctx):
        best = None
        for combo in itertools.product(range(3), repeat=3):
            ch = {f"r{i}": k for i, k in enumerate(combo)}
            s = exact_joint_score(ctx, ch)["score"]
            best = s if best is None or s < best else best
        return best

    def test_matches_exhaustive_on_tiny_cases(self):
        cfg = Config().batch
        for seed in range(6):
            for spread in (False, True):
                ctx = toy_context(seed, spread=spread)
                res = Batch(cfg).select(ctx)
                got = exact_joint_score(ctx, res.choices)["score"]
                self.assertAlmostEqual(got, self.exhaustive(ctx), delta=0.2, msg=f"seed {seed} spread {spread}")
                self.assertLessEqual(got, exact_joint_score(ctx, Heuristic().select(ctx).choices)["score"] + 1e-6)

    def test_lambda_zero_batch_is_forecast_only(self):
        ctx = toy_context(1, lam=0.0)
        self.assertEqual(Batch(Config().batch).select(ctx).choices, ForecastOnly().select(ctx).choices)

    def test_tiny_budget_still_returns_valid_plan(self):
        cfg = Config().batch
        cfg.solve_ms = 0.001
        ctx = toy_context(2)
        res = Batch(cfg).select(ctx)
        self.assertEqual(set(res.choices), {"r0", "r1", "r2"})
        self.assertIn(res.solver["kept"], ("solver", "heuristic_better_under_exact_score", "heuristic_fallback"))

    def test_request_order_sensitivity_is_reported_not_hidden(self):
        """Sequential heuristic may depend on order; the batch solver's exact score may not be worse either way."""
        ctx = toy_context(3)
        rev = SelectionContext(**{**ctx.__dict__, "items": list(reversed(ctx.items))})
        b1 = exact_joint_score(ctx, Batch(Config().batch).select(ctx).choices)["score"]
        b2 = exact_joint_score(rev, Batch(Config().batch).select(rev).choices)["score"]
        self.assertAlmostEqual(b1, b2, delta=0.2)


ML = Path(__file__).resolve().parents[1]


@unittest.skipUnless((ML / "data/sf_citywide/net_v3/arcs_c90.json").exists()
                     and (ML / "data/coordination/fixtures/forecast_fixture.parquet").exists(),
                     "net_v3 artifacts / fixture not present (python -m coordination fixture)")
class TestRealNetworkSmoke(unittest.TestCase):
    def test_end_to_end_route_on_net_v3(self):
        from coordination import config as cfg_mod
        from coordination.runtime import build
        cfg = cfg_mod.load("configs/coordinated_routing_v2.yaml")
        c = build(cfg, db_path=":memory:")
        r = c.recommend(RouteRequest("smoke", (-122.4350, 37.7625), (-122.4094, 37.7726), c.clock()))
        self.assertEqual(r["outcome"], "recommendation")
        self.assertIn("fixture_forecast", r["degradation"])
        route = r["recommended"]["road_segment_ids"]
        for x, y in zip(route, route[1:]):
            self.assertTrue(c.net.has_arc(c.net.pos[x], c.net.pos[y]))
        # no road inside a full closure at entry
        snap = c.store.current
        for road, entry, exit_, *_ in c.ledger.assignments[r["assignment"]["assignment_id"]].schedule[1:]:
            self.assertIsNone(snap.blocked(c.net.pos[road], entry, exit_))


if __name__ == "__main__":
    unittest.main()
