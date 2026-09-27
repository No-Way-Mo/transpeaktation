"""Tests for ml/forecast on a tiny hand-built fixture dataset (42 roads, 6 short runs). CPU only.

Run from ml/: python -m unittest tests.test_forecast
"""
from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import torch
    HAVE_TORCH = True
except ImportError:   # the generator does not need the training stack
    HAVE_TORCH = False

if HAVE_TORCH:
    from forecast import adapter, audit, data as data_mod, events as ev_mod, graph as graph_mod
    from forecast.config import Config, MPH_PER_MPS, save_json
    from forecast.data import PHASES, RunArrays, make_window, window_origins
    from forecast.evaluate import derive, z_bounds

T0 = pd.Timestamp("2026-10-04T18:00:00Z").timestamp()
B = 600


def _fixture(root: Path) -> "Config":
    cfg = Config()
    cfg.name = "fx_exp"
    cfg.data.out_root = str(root)
    cfg.data.dataset_id = "fx"
    cfg.graph.patch_size = 7
    cfg.model.hidden, cfg.model.heads, cfg.model.blocks, cfg.model.dropout = 16, 2, 1, 0.1
    cfg.train.device, cfg.train.amp, cfg.train.max_epochs, cfg.train.origins_per_family = "cpu", False, 3, 3
    cfg.events.context_radius_m = 1000.0
    ddir = cfg.dataset_dir
    rng = np.random.default_rng(0)
    n = 40
    ids = [f"r{i:03d}" for i in range(n)] + ["r040", "r041"]
    xy = np.array([[150.0 * (i % 8), 150.0 * (i // 8)] for i in range(n)], np.float32)
    src = np.array([i for i in range(n)] * 2)
    dst = np.array([(i + 1) % n for i in range(n)] + [(i + 8) % n for i in range(n)])
    leaves = graph_mod.balanced_patches(xy, cfg.graph.patch_size)
    patch_idx = np.full((len(leaves), cfg.graph.patch_size), -1)
    road_patch = np.zeros(n, np.int64)
    for p, l in enumerate(leaves):
        patch_idx[p, :len(l)] = l
        road_patch[l] = p
    roads = pd.DataFrame({"road_segment_id": ids, "model_idx": list(range(n)) + [-1, -1],
                          "in_sumo": [True] * n + [False, False], "car_access": "yes",
                          "gap": ["none"] * n + ["merged_parallel", "absorbed_into_junction"],
                          "represented_by": [None] * n + ["r000", None],
                          "availability_static": ["open"] * n + ["unavailable", "unavailable"]})
    g = graph_mod.RoadGraph(roads=roads, model_ids=np.array(ids[:n]), src=src, dst=dst, xy=xy,
                            length_m=np.full(n, 150.0), free_flow_mph=np.full(n, 25.0),
                            static=rng.normal(size=(n, len(graph_mod.STATIC_FEATURES))).astype(np.float32),
                            patch_idx=patch_idx, road_patch=road_patch, stats={})
    graph_mod.save(g, ddir / "graph")
    T = 22
    phase = np.array([0, 0] + [1] * 17 + [2] * 3, np.int8)
    times = (T0 + B * np.arange(T)).astype(np.int64)
    iso = lambda k: pd.Timestamp(T0 + B * k, unit="s", tz="UTC").isoformat()
    selected, win_rows = [], []
    parts = {"g0": "train", "g1": "train", "g2": "val", "g3": "test"}
    for grp, part in parts.items():
        for with_event in (True, False):
            rid = f"{grp}_{'event' if with_event else 'control'}"
            z = (0.3 + 0.2 * np.sin(np.arange(T)[:, None] / 3 + np.arange(n)[None] / 5)).astype(np.float32)
            if with_event:
                z[10:, 4:8] += 0.8
            obs = rng.random((T, n)) < 0.7
            closed = np.zeros((T, n), bool)
            if with_event:
                closed[8:15, 3] = True
            obs &= ~closed
            zz = np.where(obs, z, np.nan).astype(np.float32)
            ref = g.ref_tt_s
            tt = np.where(obs, ref * np.exp(z), np.nan).astype(np.float32)
            speed = np.where(obs, 150.0 / tt * MPH_PER_MPS, np.nan).astype(np.float32)
            cong = np.clip(1 - speed / 25.0, 0, 1).astype(np.float32)
            d = ddir / "runs" / rid
            d.mkdir(parents=True)
            for k, v in {"time": times, "phase": phase, "z": zz, "observed": obs, "closed": closed,
                         "travel_time_s": tt, "speed_mph": speed, "congestion_ratio": cong,
                         "scheduled_closed": closed.astype(np.float16)}.items():
                np.save(d / f"{k}.npy", v)
            cases = [{"case_num": "P9", "kind": "permit", "public_start": None, "public_end": None,
                      "declared_attendance": None, "restrictions": [
                          {"segment_ids": ["r030"], "restriction": "full", "begin": iso(-20), "end": iso(40)}]}]
            if with_event:
                cases.insert(0, {"case_num": "C1", "kind": "public_event", "public_start": iso(10),
                                 "public_end": iso(18), "declared_attendance": 20000.0, "restrictions": [
                                     {"segment_ids": ["r003"], "restriction": "full", "begin": iso(8), "end": iso(15)}]})
            save_json(d / "context.json", {"cases": cases})
            sel = {"run_id": rid, "family_id": f"fam_{grp}", "family_group": grp, "with_event": with_event,
                   "partition": part}
            selected.append(sel)
            for o in window_origins(phase, cfg.data.history_steps, cfg.data.horizon_steps, [1]):
                win_rows.append({**{k: sel[k] for k in ("run_id", "family_id", "family_group", "partition",
                                                           "with_event")}, "origin": int(o), "issued_at": int(times[o])})
    win = pd.DataFrame(win_rows)
    win.to_parquet(ddir / "windows.parquet", index=False)
    save_json(ddir / "manifest.json", {"network": {"version": "fx-net"}, "batch": "fx", "selected_runs": selected,
                                       "provenance": {"export_status": "fixture", "source": "fixture"}})
    save_json(ddir / "splits.json", {**{p: sorted(g for g, q in parts.items() if q == p) for p in ("train", "val", "test")},
                                     "runs": {p: sorted(s["run_id"] for s in selected if s["partition"] == p)
                                              for p in ("train", "val", "test")}})
    save_json(ddir / "norm.json", data_mod.fit_norm(cfg, g, win))
    return cfg


@unittest.skipUnless(HAVE_TORCH, "training stack (torch) not installed")
class ForecastTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.cfg = _fixture(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # --------------------------------------------------------------- causality / windows / splits
    def test_future_traffic_cannot_change_inputs(self):
        cfg = self.cfg
        norm = json.loads((cfg.dataset_dir / "norm.json").read_text())
        a = RunArrays(cfg.dataset_dir / "runs" / "g0_event")
        o = 9
        w0 = make_window(cfg, a, o, norm)
        a.z = np.array(a.z); a.z[o:] = 9.0                          # rewrite every bucket from the origin on
        a.obs = np.array(a.obs); a.obs[o:] = ~a.obs[o:]
        a.closed = np.array(a.closed); a.closed[o:] = ~a.closed[o:]
        w1 = make_window(cfg, a, o, norm)
        np.testing.assert_array_equal(w0.hist, w1.hist)
        np.testing.assert_array_equal(w0.zf_last, w1.zf_last)
        np.testing.assert_array_equal(w0.time_hist, w1.time_hist)
        self.assertEqual(w0.issued_at, int(T0 + B * o))
        self.assertFalse(np.array_equal(np.nan_to_num(w0.target_z), np.nan_to_num(w1.target_z)))

    def test_windows_stay_inside_one_run_and_demand_phase(self):
        phase = np.array([0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 2])
        o = window_origins(phase, 6, 6, [1])
        self.assertTrue(len(o) > 0)
        for x in o:
            self.assertGreaterEqual(x - 6, 0)
            self.assertLessEqual(x + 6, len(phase))
            self.assertTrue((phase[x - 6:x + 6] == 1).all())
        self.assertEqual(len(window_origins(phase[:11], 6, 6, [1])), 0)   # too short: no window invented
        win = pd.read_parquet(self.cfg.dataset_dir / "windows.parquet")
        T = 22
        self.assertTrue(((win.origin - 6 >= 0) & (win.origin + 6 <= T)).all())

    def test_split_keeps_groups_and_pairs_together(self):
        groups = [f"e{i}" for i in range(8)]
        s = audit.split_groups(groups, Config())
        allp = s["train"] + s["val"] + s["test"]
        self.assertEqual(sorted(allp), sorted(groups))
        self.assertEqual(len(set(allp)), len(allp))
        self.assertEqual((len(s["train"]), len(s["val"]), len(s["test"])), (6, 1, 1))
        self.assertEqual(s, audit.split_groups(list(reversed(groups)), Config()))   # deterministic
        self.assertIn("development", audit.split_groups(groups[:3], Config())["kind"])
        win = pd.read_parquet(self.cfg.dataset_dir / "windows.parquet")
        self.assertTrue((win.groupby("family_group").partition.nunique() == 1).all())
        self.assertTrue((win.groupby("family_id").partition.nunique() == 1).all())
        real = Path(__file__).resolve().parents[1] / "data/forecast/datasets/b3_verify_v3net_ep1/windows.parquet"
        if real.exists():
            rw = pd.read_parquet(real)
            self.assertTrue((rw.groupby("family_group").partition.nunique() == 1).all())

    # --------------------------------------------------------------- graph / model numerics
    def test_graph_and_patch_mappings_preserve_road_ids(self):
        rng = np.random.default_rng(1)
        xy = rng.random((1000, 2)) * 5000
        leaves = graph_mod.balanced_patches(xy, 128)
        allidx = np.concatenate(leaves)
        self.assertEqual(sorted(allidx.tolist()), list(range(1000)))
        self.assertLessEqual(max(map(len, leaves)), 128)
        from forecast.model import GraphBuffers
        g = graph_mod.load(self.cfg.dataset_dir / "graph")
        gb = GraphBuffers(torch.as_tensor(g.patch_idx), torch.as_tensor(g.road_patch), torch.as_tensor(g.src),
                          torch.as_tensor(g.dst), torch.as_tensor(g.static))
        flat = gb.patch_idx.reshape(-1)
        self.assertTrue(torch.equal(flat[gb.road_slot], torch.arange(g.n)))   # road -> slot -> same road
        self.assertEqual(list(g.model_ids), [f"r{i:03d}" for i in range(40)])
        hops = graph_mod.bfs_hops(g.n, g.src, g.dst, np.array([0]), 3)
        self.assertEqual(hops[0], 0); self.assertEqual(hops[1], 1); self.assertEqual(hops[8], 1)
        self.assertEqual(hops[39], 4)   # not reachable within 3 hops along i+1 / i+8 arcs

    def test_padding_and_missing_values_do_not_create_nans(self):
        from forecast.model import build_model
        from forecast.train import Data, forward, loss_fn, to_batch
        cfg = self.cfg
        d = Data(cfg, torch.device("cpu"))
        self.assertTrue((d.graph.patch_idx < 0).any())             # fixture patches include padding slots
        model = build_model(cfg, d.graph, d.norm, len(ev_mod.EVENT_PAIR_FEATURES))
        r = d.partition("train").iloc[0]
        w = d.window(r)
        w.hist[:, :10] = data_mod.normalize_hist(data_mod.history_features(
            np.full((6, 10), np.nan, np.float32), np.zeros((6, 10), bool), np.zeros((6, 10), bool), 2)[0], d.norm)
        self.assertTrue(np.isfinite(w.hist).all())
        self.assertTrue((w.hist[:, :10, data_mod.HIST_FEATURES.index("missing_after_fill")] == 1).all())
        b = to_batch(w, torch.device("cpu"), d.event_tensors(r.run_id), cfg)
        p = forward(model, b, False)
        self.assertTrue(torch.isfinite(p).all())
        loss_fn(cfg, p, b).backward()
        self.assertTrue(all(torch.isfinite(q.grad).all() for q in model.parameters() if q.grad is not None))
        # valid zero congestion is distinguishable from missing
        f, _ = data_mod.history_features(np.zeros((6, 1), np.float32), np.ones((6, 1), bool), np.zeros((6, 1), bool), 2)
        g_, _ = data_mod.history_features(np.full((6, 1), np.nan, np.float32), np.zeros((6, 1), bool), np.zeros((6, 1), bool), 2)
        self.assertFalse(np.allclose(np.nan_to_num(f), np.nan_to_num(g_)))

    def test_forward_fill_at_most_two_buckets(self):
        z = np.array([[0.5], [np.nan], [np.nan], [np.nan], [np.nan], [0.2]], np.float32)
        obs = np.isfinite(z)
        f, zf = data_mod.history_features(z, obs, np.zeros_like(obs), 2)
        np.testing.assert_allclose(zf[:, 0], [0.5, 0.5, 0.5, np.nan, np.nan, 0.2])
        self.assertEqual(f[1, 0, data_mod.HIST_FEATURES.index("ffilled")], 1)
        self.assertEqual(f[3, 0, data_mod.HIST_FEATURES.index("missing_after_fill")], 1)

    def test_event_branch_identity_init_and_schedule_influence(self):
        from forecast.model import build_model
        from forecast.train import Data, forward, to_batch
        cfg = self.cfg
        d = Data(cfg, torch.device("cpu"))
        torch.manual_seed(0)
        model = build_model(cfg, d.graph, d.norm, len(ev_mod.EVENT_PAIR_FEATURES)).eval()
        r = d.partition("train").query("with_event").iloc[0]
        w = d.window(r)
        ctx = json.loads(json.dumps(d.run(r.run_id).context))
        moved = json.loads(json.dumps(ctx))
        moved["cases"][0]["public_start"] = pd.Timestamp(T0 + B * 40, unit="s", tz="UTC").isoformat()
        moved["cases"][0]["public_end"] = pd.Timestamp(T0 + B * 50, unit="s", tz="UTC").isoformat()
        run = lambda c: forward(model, to_batch(w, torch.device("cpu"), d.event_tensors(r.run_id, context=c), cfg), False)
        with torch.no_grad():
            self.assertTrue(torch.equal(run(ctx), run(moved)))   # zero-initialised conditioning = exact no-op
            for m in [*model.events.film, model.events.dec_ctx, model.events.dec_film]:
                torch.nn.init.normal_(m.weight, std=0.1)
            p0, p1 = run(ctx), run(moved)
        self.assertGreater(float((p0 - p1).abs().max()), 1e-5)   # future schedule reaches the predictions
        b = to_batch(w, torch.device("cpu"), d.event_tensors(r.run_id), cfg)
        model.train()
        from forecast.losses import masked_huber
        masked_huber(forward(model, b, False), b["target"], b["mask"]).backward()
        self.assertGreater(float(model.events.pair[0].weight.grad.abs().sum()), 0)

    # --------------------------------------------------------------- outputs
    def test_travel_time_speed_congestion_consistent(self):
        g = graph_mod.load(self.cfg.dataset_dir / "graph")
        _, zmax = z_bounds(g)
        z = np.stack([np.linspace(-2, 6, g.n)] * 3).astype(np.float32)
        p = derive(z, g)
        np.testing.assert_allclose(p["speed"] / MPH_PER_MPS * p["tt"], np.broadcast_to(g.length_m, z.shape), rtol=1e-5)
        np.testing.assert_allclose(p["cong"], np.clip(1 - p["speed"] / g.free_flow_mph, 0, 1), atol=1e-6)
        self.assertTrue((p["tt"] > 0).all())
        self.assertTrue((p["cong"] <= 1).all() and (p["cong"] >= 0).all())
        self.assertTrue(np.isclose(p["z"].max(), zmax.max()))     # severe congestion kept up to the 0.1 m/s floor
        self.assertGreater(p["cong"].max(), 0.99)

    def test_training_resume_restores_experiment(self):
        from forecast.train import train, load_checkpoint
        a, b = copy.deepcopy(self.cfg), copy.deepcopy(self.cfg)
        a.name, b.name = "resume_straight", "resume_split"
        train(a, log=lambda m: None)
        train(b, log=lambda m: None, stop_after_epochs=1)
        self.assertEqual(load_checkpoint(b.exp_dir / "last.pt")["state"]["epoch"], 1)
        train(b, resume=True, log=lambda m: None)
        ca, cb = load_checkpoint(a.exp_dir / "last.pt"), load_checkpoint(b.exp_dir / "last.pt")
        for k in ca["model"]:
            self.assertTrue(torch.equal(ca["model"][k], cb["model"][k]), k)
        self.assertEqual([r["train_loss"] for r in ca["state"]["curves"]], [r["train_loss"] for r in cb["state"]["curves"]])
        self.assertEqual(ca["state"]["best_epoch"], cb["state"]["best_epoch"])
        with self.assertRaises(SystemExit):   # silently mixing a changed config into a resume is refused
            b.train.lr = 0.5
            train(b, resume=True, log=lambda m: None)

    def test_predict_export_timestamps_units_and_closures(self):
        from forecast.predict import predict
        from forecast.train import train
        cfg = copy.deepcopy(self.cfg)
        cfg.name = "predict_fx"
        cfg.train.max_epochs = 1
        train(cfg, log=lambda m: None)
        snap = self.tmp / "snap"
        snap.mkdir()
        a = RunArrays(cfg.dataset_dir / "runs" / "g2_event")
        o = 10
        issued = pd.Timestamp(T0 + B * o, unit="s", tz="UTC")
        rows = []
        ids = [f"r{i:03d}" for i in range(42)]
        for t in range(o - 6, o):
            sp = np.concatenate([np.asarray(a.speed[t]), [np.nan, np.nan]])
            ob = np.concatenate([np.asarray(a.obs[t]), [False, False]])
            cl = np.concatenate([np.asarray(a.closed[t]), [False, False]])
            rows.append(pd.DataFrame({"time": pd.Timestamp(T0 + B * t, unit="s", tz="UTC"), "road_segment_id": ids,
                                      "speed_mph": sp, "observed": ob, "closed": cl}))
        pd.concat(rows).to_parquet(snap / "history.parquet", index=False)
        ctx = dict(a.context, issued_at=issued.isoformat(), network_version="fx-net",
                   provenance={"source": "fixture", "synthetic": True})
        save_json(snap / "context.json", ctx)
        out = self.tmp / "fc" / "forecast.parquet"
        predict(str(cfg.exp_dir / "last.pt"), str(snap), str(out))
        f = pd.read_parquet(out)
        self.assertEqual(len(f), 42 * 6)
        self.assertEqual(sorted(f.horizon_min.unique()), [10, 20, 30, 40, 50, 60])
        k = (f.horizon_min // 10 - 1).to_numpy()
        vf = pd.to_datetime(f.valid_from, utc=True)
        self.assertTrue((vf == issued + pd.to_timedelta(10 * k, unit="min")).all())
        self.assertTrue((pd.to_datetime(f.valid_to, utc=True) - vf == pd.Timedelta(minutes=10)).all())
        m = f[f.prediction_source == "model"]
        np.testing.assert_allclose(m.predicted_speed_mph / MPH_PER_MPS * m.predicted_travel_time_sec, 150.0, rtol=1e-5)
        # r003 is closed [bucket 8, bucket 15): horizons covering buckets 10..14 are closed, bucket 15 open
        r3 = f[f.road_segment_id == "r003"].sort_values("horizon_min")
        self.assertEqual(r3.availability.tolist(), ["closed"] * 5 + ["open"])
        self.assertTrue(r3.predicted_travel_time_sec.iloc[:5].isna().all())
        # explicit representative mapping and no invented predictions for unrepresented roads
        r40 = f[f.road_segment_id == "r040"]
        self.assertTrue((r40.prediction_source == "representative_road").all() and (r40.represented_by == "r000").all())
        r41 = f[f.road_segment_id == "r041"]
        self.assertTrue((r41.availability == "unavailable").all() and r41.predicted_travel_time_sec.isna().all())
        self.assertFalse(any("confidence" in c for c in f.columns))
        self.assertTrue((f.input_source == "fixture").all() and f.model_version.notna().all())

    def test_closures_override_routing_at_the_right_time(self):
        issued = pd.Timestamp("2026-10-04T18:00:00Z")
        ids = ["a", "b", "c", "d"]
        rows = []
        for r in ids:
            for k in range(6):
                vf = issued + pd.Timedelta(minutes=10 * k)
                rows.append({"road_segment_id": r, "issued_at": issued, "valid_from": vf,
                             "valid_to": vf + pd.Timedelta(minutes=10), "horizon_min": 10 * (k + 1),
                             "predicted_travel_time_sec": 60.0 if r != "d" else 600.0, "availability": "open",
                             "restriction_reason": "none", "prediction_source": "model"})
        fc = pd.DataFrame(rows)
        closures = pd.DataFrame([{"road_segment_id": "b", "restriction": "full",
                                  "closure_begin": issued + pd.Timedelta(minutes=15),
                                  "closure_end": issued + pd.Timedelta(minutes=40)}])
        arcs = [("a", "b"), ("b", "c"), ("a", "d"), ("d", "c")]
        rt = adapter.ForecastRouter(fc, closures, arcs)
        early = rt.route("a", "c", issued)                                     # enters b at +1 min: open
        self.assertEqual(early.path, ["a", "b", "c"])
        self.assertAlmostEqual(early.travel_time_sec, 180.0)
        during = rt.route("a", "c", issued + pd.Timedelta(minutes=14))        # enters b at +15 min: closed
        self.assertEqual(during.path, ["a", "d", "c"])
        self.assertAlmostEqual(during.travel_time_sec, 720.0)
        after = rt.route("a", "c", issued + pd.Timedelta(minutes=39))         # enters b at +40 min: reopened
        self.assertEqual(after.path, ["a", "b", "c"])
        late = rt.route("a", "c", issued + pd.Timedelta(minutes=59, seconds=30))
        self.assertTrue(late.reachable and late.beyond_horizon)
        fc2 = fc.copy()
        fc2.loc[(fc2.road_segment_id == "d") & (fc2.horizon_min == 20), "availability"] = "closed"
        blocked = adapter.ForecastRouter(fc2, closures, arcs).route("a", "c", issued + pd.Timedelta(minutes=14))
        self.assertFalse(blocked.reachable)                                     # both branches closed at entry
        eta = rt.many_to_one(["a", "d"], "c", issued)
        self.assertEqual(eta.vehicle_road.tolist(), ["a", "d"])


if __name__ == "__main__":
    unittest.main()
