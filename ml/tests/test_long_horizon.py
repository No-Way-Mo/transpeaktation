"""Long-horizon retraining (LONG_HORIZON_RETRAINING_PLAN.md): planner windows, lead bands, migration, grouped loss."""
import unittest

import numpy as np
import torch

from eventsim import citywide_batch as cb
from forecast import event_windows as ew
from forecast import retrain as rt
from forecast.model import EventPatchForecaster, GraphBuffers


def tiny(H):
    torch.manual_seed(0)
    gb = GraphBuffers(torch.tensor([[0, 1], [2, -1]]), torch.tensor([0, 0, 1]), torch.tensor([0, 1]),
                      torch.tensor([1, 2]), torch.zeros(3, 4))
    return EventPatchForecaster(gb, 8, 4, 1, 5, 6, H, hidden=8, heads=2, blocks=1)


class LongHorizon(unittest.TestCase):
    def test_planner_window(self):
        a, b = cb.long_bounds("arrival", (11, 18), 180)
        self.assertEqual((a, b), (11 * 3600 - 240 * 60 - cb.WARMUP_S, 11 * 3600 + 210 * 60 + cb.DRAIN_S))
        s, e = cb.window_for("departure", (13, 23), 180)
        self.assertEqual(e, 24 * 3600 - 600)                  # clamped to the event day, no cross-midnight run
        self.assertEqual(s, 23 * 3600 - 240 * 60 - cb.WARMUP_S)

    def test_lead_bands(self):
        start, end = 10_000.0 * 60, 10_300.0 * 60
        issued = np.array([10_000 - 30, 10_000 - 61, 10_000 - 180, 10_000 - 181, 10_300 - 150, 10_300 - 10, 10_000 + 5]) * 60.0
        cat = ew.lead_category(issued, start, end, [0, 60, 120, 180])
        self.assertEqual(list(cat), ["start_0_60", "start_60_120", "start_120_180", "other", "end_120_180", "end_0_60", "other"])

    def test_migration_keeps_parent_rows(self):
        parent, new = tiny(6), tiny(18)
        with torch.no_grad():
            for p in parent.parameters():
                p.add_(torch.randn_like(p))
        log = rt.migrate(new, parent.state_dict(), 0.01, 0)
        self.assertTrue(torch.equal(new.hor.weight[:6], parent.hor.weight))
        self.assertTrue(torch.isfinite(new.hor.weight[6:]).all())
        self.assertFalse(torch.equal(new.hor.weight[6:7], parent.hor.weight[-1:]))
        for k, v in parent.state_dict().items():
            if k != "hor.weight":
                self.assertTrue(torch.equal(new.state_dict()[k], v), k)
        self.assertEqual(log["grown"]["hor.weight"]["new_rows"], 12)
        with self.assertRaises(SystemExit):     # a real shape mismatch is an error, not silently skipped
            rt.migrate(tiny(18), {**parent.state_dict(), "head.0.weight": torch.zeros(3, 3)}, 0.01, 0)

    def test_all_parameters_train(self):
        m = tiny(18)
        groups = rt.param_groups(m, rt.RetrainCfg())
        self.assertEqual(sum(p.numel() for g in groups for p in g["params"]), sum(p.numel() for p in m.parameters()))
        self.assertTrue(all(p.requires_grad for p in m.parameters()))

    def test_grouped_loss(self):
        pred = torch.zeros(1, 18, 4, requires_grad=True)
        tgt = torch.ones(1, 18, 4)
        mask = torch.zeros(1, 18, 4, dtype=torch.bool)
        mask[:, :6] = True
        g = [[0, 6, 0.5], [6, 18, 0.5]]
        self.assertAlmostEqual(float(rt.hgroup_huber(pred, tgt, mask, g)), 0.5)   # empty group drops out
        mask[:, 6:, 0] = True
        tgt2 = tgt.clone()
        tgt2[:, 6:] = 3.0
        self.assertAlmostEqual(float(rt.hgroup_huber(pred, tgt2, mask, g)), 0.5 * 0.5 + 0.5 * 2.5)
        empty = rt.hgroup_huber(pred, tgt, torch.zeros_like(mask), g)
        empty.backward()
        self.assertEqual(float(empty), 0.0)


if __name__ == "__main__":
    unittest.main()


class Improvements(unittest.TestCase):
    """EVENT_ANTICIPATION_IMPROVEMENTS_PLAN.md: heads, extra event features, objective terms."""

    def test_heads_and_grown_event_input_migrate(self):
        torch.manual_seed(0)
        gb = lambda: GraphBuffers(torch.tensor([[0, 1], [2, -1]]), torch.tensor([0, 0, 1]), torch.tensor([0, 1]),
                                  torch.tensor([1, 2]), torch.zeros(3, 4))
        parent = EventPatchForecaster(gb(), 8, 4, 1, 5, 6, 6, hidden=8, heads=2, blocks=1)
        child = EventPatchForecaster(gb(), 8, 4, 1, 7, 6, 18, hidden=8, heads=2, blocks=1, jam_head=True,
                                     quantiles=[0.1, 0.9])
        log = rt.migrate(child, parent.state_dict(), 0.01, 0)
        w_new, w_old = child.state_dict()["events.pair.0.weight"], parent.state_dict()["events.pair.0.weight"]
        self.assertTrue(torch.equal(w_new[:, :5], w_old))
        self.assertTrue(torch.equal(w_new[:, 5:], torch.zeros_like(w_new[:, 5:])))
        self.assertIn("jam_head.2.bias", log["grown"])
        x = dict(hist=torch.randn(1, 6, 3, 8), time_hist=torch.randn(1, 6, 4), time_fut=torch.randn(1, 18, 4),
                 fut_base=torch.randn(1, 18, 3, 1), event_feats=torch.randn(1, 19, 2, 7), pair_road=torch.tensor([0, 2]))
        child.eval()
        out = child(**x, aux=True)
        self.assertEqual(out["jam_logit"].shape, (1, 18, 3))
        self.assertTrue((out["z_q"][..., 0] <= out["z"]).all() and (out["z_q"][..., 1] >= out["z"]).all())
        self.assertTrue(torch.equal(child(**x), out["z"]))

    def test_tolerant_jam_labels(self):
        thr_z = float(np.log(2.0))
        tgt = torch.zeros(1, 6, 2)
        tgt[0, 3, 0] = thr_z + 0.1
        mask = torch.ones(1, 6, 2, dtype=torch.bool)
        y0 = rt.jam_labels({"target": tgt, "mask": mask}, 0.5, 0)
        y2 = rt.jam_labels({"target": tgt, "mask": mask}, 0.5, 2)
        self.assertEqual(y0[0, :, 0].tolist(), [0, 0, 0, 1, 0, 0])
        self.assertEqual(y2[0, :, 0].tolist(), [0, 1, 1, 1, 1, 1])
        self.assertEqual(float(y2[0, :, 1].sum()), 0.0)

    def test_objective_with_heads(self):
        z = torch.zeros(1, 18, 4, requires_grad=True)
        out = {"z": z, "jam_logit": torch.zeros(1, 18, 4, requires_grad=True),
               "z_q": torch.stack([z - 0.1, z + 0.1], -1), "_quantiles": [0.1, 0.9]}
        b = {"target": torch.ones(1, 18, 4), "mask": torch.ones(1, 18, 4, dtype=torch.bool)}
        mk = {k: b["mask"] for k in ("global", "event_near", "anticipation")}
        rc = rt.RetrainCfg(jam_weight=1.0, quantile_weight=0.5, jam_tolerance=1)
        tot, info = rt.objective(out, b, mk, rc, 1.0)
        tot.backward()
        self.assertTrue(np.isfinite(float(tot)) and "jam_global" in info and "q_anticipation" in info)
        self.assertIsNotNone(out["jam_logit"].grad)

    def test_route_loads(self):
        from forecast import events as ev_mod

        class G:   # a 5-road chain 0 -> 1 -> 2 -> 3 -> 4, footprint = road 4
            n = 5
            src, dst = np.array([0, 1, 2, 3]), np.array([1, 2, 3, 4])
            ref_tt_s = np.ones(5)
            xy = np.column_stack([np.arange(5) * 100.0, np.zeros(5)])
        li, lo = ev_mod.route_loads(G, np.array([4]))
        self.assertAlmostEqual(li.sum(), 1.0)
        self.assertTrue(li[3] > li[2] > li[1] > li[0])        # inbound demand accumulates toward the footprint
        self.assertAlmostEqual(lo[:4].sum(), 0.0)             # nothing leaves road 4 on this chain

    def test_onset_features(self):
        from forecast import events as ev_mod
        from forecast.data import HIST_FEATURES
        ev = ev_mod.EventTensors(np.array([0, 0]), np.array([0, 1]), np.zeros((2, 6), np.float32), np.full(2, np.nan),
                                 np.full(2, np.nan), np.zeros((1, 5), np.float32), np.zeros((1, 4))).to_torch("cpu")
        ev.pair_static[:, ev_mod.PAIR_STATIC.index("prox_1000m")] = torch.tensor([1.0, 0.1])   # only road 0 is near
        hist = torch.zeros(6, 2, len(HIST_FEATURES))
        hist[:, 0, HIST_FEATURES.index("z_filled")] = torch.arange(6.0)
        hist[:, 1, HIST_FEATURES.index("z_filled")] = 100.0
        f = ev_mod.onset_features(ev, hist)
        self.assertEqual(f.shape, (1, 4))
        self.assertAlmostEqual(float(f[0, 0]), 5.0)          # last bucket, near road only
        self.assertAlmostEqual(float(f[0, 1]), 4.0)          # mean of the last 3
        self.assertAlmostEqual(float(f[0, 2]), 5.0)          # last - first


class Round2(unittest.TestCase):
    def test_attention_pooling_migrates_and_ensemble_averages(self):
        from forecast.model import Ensemble
        torch.manual_seed(0)
        gb = lambda: GraphBuffers(torch.tensor([[0, 1], [2, -1]]), torch.tensor([0, 0, 1]), torch.tensor([0, 1]),
                                  torch.tensor([1, 2]), torch.zeros(3, 4))
        parent = EventPatchForecaster(gb(), 8, 4, 1, 5, 6, 6, hidden=8, heads=2, blocks=1)
        child = EventPatchForecaster(gb(), 8, 4, 1, 5, 6, 18, hidden=8, heads=2, blocks=1, event_attn_pool=True,
                                     jam_head=True)
        log = rt.migrate(child, parent.state_dict(), 0.01, 0)
        self.assertEqual(log["grown"]["events.agg.0.weight"]["new_cols"], 8)
        self.assertTrue(torch.equal(child.state_dict()["events.agg.0.weight"][:, :17], parent.state_dict()["events.agg.0.weight"]))
        x = dict(hist=torch.randn(1, 6, 3, 8), time_hist=torch.randn(1, 6, 4), time_fut=torch.randn(1, 18, 4),
                 fut_base=torch.randn(1, 18, 3, 1), event_feats=torch.randn(1, 19, 3, 5),
                 pair_road=torch.tensor([0, 0, 2]))
        child.eval()
        z1 = child(**x)
        self.assertTrue(torch.isfinite(z1).all())
        ens = Ensemble([child, child]).eval()
        o = ens(**x, aux=True)
        self.assertTrue(torch.allclose(o["z"], z1, atol=1e-6))
        self.assertTrue(torch.allclose(torch.sigmoid(o["jam_logit"]), torch.sigmoid(child(**x, aux=True)["jam_logit"]), atol=1e-5))
