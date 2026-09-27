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
