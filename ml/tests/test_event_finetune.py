"""Event-awareness fine-tuning on the tiny forecast fixture (CPU): freezing, gradients through frozen blocks, pairing,
clear-road masks, empty/NaN-safe losses, teacher immutability, resume, no test leakage, checkpoint compatibility.

Run from ml/: python -m unittest tests.test_event_finetune
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

try:
    import torch
    HAVE_TORCH = True
except ImportError:
    HAVE_TORCH = False

if HAVE_TORCH:
    from forecast import event_windows as ew
    from forecast import finetune as ft
    from forecast.config import read_json, save_json, sha256_file
    from forecast.losses import masked_huber, paired_delta_huber
    from forecast.train import Data, load_checkpoint, train
    from tests.test_forecast import B, T0, _fixture


def _prepare(root: Path):
    """Fixture + a trained parent + the manifest fields the fine-tuner verifies (seed, window, cache markers)."""
    cfg = _fixture(root)
    cfg.train.max_epochs = 2
    train(cfg, log=lambda m: None)
    ddir = cfg.dataset_dir
    man = read_json(ddir / "manifest.json")
    man["input_sha256"] = {}
    for r in man["selected_runs"]:
        r["seed"], r["window"] = 7, "full"
        fake = hashlib.sha256(r["run_id"].encode()).hexdigest()
        man["input_sha256"][f"export/sim_{r['run_id']}.parquet"] = fake
        save_json(ddir / "runs" / r["run_id"] / "done.json", {"source_sha256": fake})
    save_json(ddir / "manifest.json", man)
    # the parent was trained before the manifest edit: re-stamp its manifest digest (fixture only)
    ck = load_checkpoint(cfg.exp_dir / "best.pt")
    ck["dataset_manifest_sha256"] = sha256_file(ddir / "manifest.json")
    torch.save(ck, cfg.exp_dir / "best.pt")
    spec = ft.Spec(parent=str(cfg.exp_dir / "best.pt"), noevent_reference=str(root / "none.pt"), output="ft_fx",
                   max_epochs=2, patience=5, stage_b_max_epochs=1, per_family=4, device="cpu",
                   lr_event=5e-3, stage_b_lr_event=5e-3, stage_b_lr_decoder=5e-3)
    return cfg, spec


@unittest.skipUnless(HAVE_TORCH, "training stack (torch) not installed")
class EventFinetuneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.cfg, cls.spec = _prepare(cls.tmp)
        cls.data = Data(cls.cfg, torch.device("cpu"))
        cls.index, cls.audit = ew.build_index(cls.cfg, cls.data)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def spec_copy(self, **kw):
        s = copy.deepcopy(self.spec)
        for k, v in kw.items():
            setattr(s, k, v)
        return s

    # ------------------------------------------------------------ index, pairs, phases, clear roads
    def test_pairs_match_family_seed_and_timestamp(self):
        w = self.index
        ev = w[w.with_event]
        self.assertTrue((ev.pair >= 0).all())
        for r in ev.itertuples():
            c = w.loc[r.pair]
            self.assertFalse(c.with_event)
            self.assertEqual((c.family_id, c.seed, c.issued_at, c.partition), (r.family_id, r.seed, r.issued_at, r.partition))
        self.assertEqual(self.audit["event_windows_without_control"], 0)

    def test_ambiguous_event_runs_are_rejected(self):
        d = Data(self.cfg, torch.device("cpu"))
        man_p = self.cfg.dataset_dir / "manifest.json"
        orig = man_p.read_text()
        try:
            man = json.loads(orig)
            for r in man["selected_runs"]:
                if r["run_id"] == "g1_event":
                    r["family_id"] = "fam_g0"              # two event runs for (fam_g0, seed 7)
            man_p.write_text(json.dumps(man))
            with self.assertRaises(SystemExit):
                ew.build_index(self.cfg, d, counts=False)
        finally:
            man_p.write_text(orig)

    def test_phases_from_schedule(self):
        w = self.index
        ps = T0 + 10 * B                                   # fixture public start = bucket 10
        pre = w[(w.issued_at >= ps - 3600) & (w.issued_at < ps)]
        self.assertTrue(pre.pre_start.all() and len(pre))
        self.assertTrue((w.loc[w.pre_start, "phase"] == "pre_start").all())
        ctl = w[~w.with_event & w.pre_start]
        self.assertTrue(len(ctl))                          # controls take the matched event's schedule

    def test_clear_roads_require_direct_observation(self):
        class A:
            pass
        a = A()
        n = 6
        a.z = np.full((3, n), 0.1, np.float32)             # congestion ~0.095: clear
        a.obs = np.ones((3, n), bool)
        a.closed = np.zeros((3, n), bool)
        a.obs[2, 1] = False                                # missing in the last bucket (would be forward-filled)
        a.closed[2, 2] = True                              # closed
        a.z[2, 3] = 1.0                                    # congested (0.63)
        a.z[2, 4] = np.nan                                 # NaN
        a.obs[1, 5] = False                                # fine now, missing one bucket earlier
        c1 = ew.clear_roads(a, 3)
        c2 = ew.clear_roads(a, 3, strict=True)
        self.assertEqual(c1.tolist(), [True, False, False, False, False, True])
        self.assertEqual(c2.tolist(), [True, False, False, False, False, False])

    def test_anticipation_keeps_future_negatives(self):
        w = self.index[self.index.with_event & self.index.pre_start]
        self.assertTrue(((w.antic_labels - w.antic_positives) > 0).any())

    # ------------------------------------------------------------ losses
    def test_empty_and_nan_masks_give_finite_zero_gradients(self):
        pred = torch.randn(1, 6, 10, requires_grad=True)
        tgt = torch.full((1, 6, 10), float("nan"))
        m = torch.zeros(1, 6, 10, dtype=torch.bool)
        l = masked_huber(pred, torch.nan_to_num(tgt), m) + paired_delta_huber(pred, pred.detach(), tgt.nan_to_num(),
                                                                              tgt.nan_to_num(), m)
        l.backward()
        self.assertEqual(float(l), 0.0)
        self.assertTrue(torch.isfinite(pred.grad).all())

    def test_paired_loss_uses_differences_only_on_common_roads(self):
        pe = torch.zeros(1, 1, 3, requires_grad=True)
        pc = torch.zeros(1, 1, 3)
        te, tc = torch.tensor([[[1.0, 5.0, 0.0]]]), torch.tensor([[[0.5, float("nan"), 0.0]]])
        common = torch.tensor([[[True, False, True]]])
        l = paired_delta_huber(pe, pc, te, tc.nan_to_num(), common)
        self.assertAlmostEqual(float(l), (0.5 * 0.5 ** 2 + 0.0) / 2, places=6)

    # ------------------------------------------------------------ training behaviour
    def test_preflight_and_gradients_reach_event_encoder(self):
        pf = ft.preflight(self.spec_copy(output="ft_pf"), "event")
        self.assertTrue(pf["ok"], pf["problems"])
        self.assertTrue(pf["checks"]["profile_step"]["grad_reaches_event_encoder"])
        self.assertTrue(pf["checks"]["profile_step"]["frozen_have_no_grad"])

    def test_stage_a_trains_only_event_branch_and_teacher_is_immutable(self):
        sha_before = sha256_file(Path(self.spec.parent))
        res = ft.finetune(self.spec_copy(output="ft_a", max_epochs=1), "event", log=lambda m: None)
        fc = res["decision"]["frozen_check"]
        self.assertEqual(fc["frozen_changed"], [])
        self.assertGreater(fc["trainable_changed"], 0)
        self.assertEqual(sha_before, sha256_file(Path(self.spec.parent)))
        od = self.cfg.path(self.cfg.data.out_root) / "experiments" / "ft_a"
        last = load_checkpoint(od / "last.pt")
        parent = load_checkpoint(self.spec.parent)
        for k, v in last["model"].items():
            if not k.startswith("events."):
                self.assertTrue(torch.equal(v, parent["model"][k]), k)
        self.assertNotEqual(last["config_hash"], parent["config_hash"])
        self.assertEqual(last["finetune"]["parent_sha256"], sha_before)
        self.assertTrue((od / "promotion_decision.json").exists())

    def test_stage_b_changes_only_allowed_groups(self):
        ft.finetune(self.spec_copy(output="ft_b"), "decoder", log=lambda m: None)
        od = self.cfg.path(self.cfg.data.out_root) / "experiments" / "ft_b_decoder"
        last, parent = load_checkpoint(od / "last.pt"), load_checkpoint(self.spec.parent)
        allowed = ("events.", "head.", "dec_ln.")
        changed = [k for k, v in last["model"].items() if not torch.equal(v, parent["model"][k])]
        self.assertTrue(changed)
        self.assertTrue(all(k.startswith(allowed) for k in changed), changed)
        self.assertTrue(any(k.startswith("head.") for k in changed))

    def test_resume_reproduces_uninterrupted_run(self):
        a = ft.finetune(self.spec_copy(output="ft_straight"), "event", log=lambda m: None)
        ft.finetune(self.spec_copy(output="ft_split"), "event", log=lambda m: None, stop_after_epochs=1)
        ft.finetune(self.spec_copy(output="ft_split"), "event", resume=True, log=lambda m: None)
        root = self.cfg.path(self.cfg.data.out_root) / "experiments"
        la, lb = load_checkpoint(root / "ft_straight" / "last.pt"), load_checkpoint(root / "ft_split" / "last.pt")
        for k in la["model"]:
            self.assertTrue(torch.equal(la["model"][k], lb["model"][k]), k)
        with self.assertRaises(SystemExit):             # a changed spec cannot resume the same experiment
            ft.finetune(self.spec_copy(output="ft_split", lr_event=1.0), "event", resume=True, log=lambda m: None)

    def test_sampler_never_draws_validation_or_test_windows(self):
        rng = np.random.default_rng(0)
        for _ in range(5):
            idx, _ = ew.epoch_sample(self.index, 6, rng)
            self.assertTrue((self.index.loc[idx, "partition"] == "train").all())

    def test_candidate_loads_through_predictor_and_evaluate(self):
        from forecast.evaluate import evaluate
        from forecast.predict import Predictor
        ft.finetune(self.spec_copy(output="ft_load", max_epochs=1), "event", log=lambda m: None)
        od = self.cfg.path(self.cfg.data.out_root) / "experiments" / "ft_load"
        ck = od / ("best.pt" if (od / "best.pt").exists() else "best_unsafe.pt")
        if not ck.exists():
            ck = od / "last.pt"
        p = Predictor(str(ck), "cpu")
        self.assertEqual(p.model_ids if hasattr(p, "model_ids") else p.ck["model_ids"], load_checkpoint(ck)["model_ids"])
        res = evaluate(str(ck), "val")
        self.assertGreater(res["coverage"]["labels"], 0)
        out = ft.evaluate_candidates(self.spec_copy(output="ft_load"), "val", {"cand": str(ck)}, log=lambda m: None)
        self.assertIn("cand", out["headline"])
        self.assertIn("parent", out["headline"])


if __name__ == "__main__":
    unittest.main()
