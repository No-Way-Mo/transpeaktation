"""Serving pointer / promotion rules (python -m unittest tests.test_forecast_serving)."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

try:
    import torch
    HAVE_TORCH = True
except ImportError:
    HAVE_TORCH = False

if HAVE_TORCH:
    from forecast import serving


def _ckpt(d: Path, name: str, decision: dict | None) -> Path:
    d = d / name
    d.mkdir(parents=True)
    torch.save({"model_version": f"{name}-v", "network_version": "net", "dataset_id": "ds", "model": {}}, d / "best.pt")
    if decision is not None:
        (d / "promotion_decision.json").write_text(json.dumps(decision))
    return d / "best.pt"


@unittest.skipUnless(HAVE_TORCH, "torch not installed")
class ServingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.sd = self.tmp / "serving"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_ordinary_checkpoint_promotes_and_resolves(self):
        p = _ckpt(self.tmp, "parent", None)
        rec = serving.promote(str(p), "baseline", serving_dir=self.sd)
        self.assertEqual(rec["validation_rule"], "none (ordinary trained checkpoint)")
        path, got = serving.resolve(serving_dir=self.sd)
        self.assertEqual(got["sha256"], rec["sha256"])
        self.assertTrue(path.exists())

    def test_failed_candidate_needs_force_and_is_recorded(self):
        p = _ckpt(self.tmp, "cand", {"promote": False, "validation": {"antic_tt_mae": 1.0}})
        with self.assertRaises(SystemExit):
            serving.promote(str(p), "try", serving_dir=self.sd)
        self.assertIsNone(serving.current(self.sd))
        rec = serving.promote(str(p), "owner asked", force=True, serving_dir=self.sd)
        self.assertTrue(rec["forced"])
        self.assertEqual(rec["validation_rule"], "NOT passed (forced)")

    def test_history_keeps_previous_and_tampering_is_detected(self):
        a = _ckpt(self.tmp, "a", None)
        b = _ckpt(self.tmp, "b", {"promote": True})
        serving.promote(str(a), "first", serving_dir=self.sd)
        rec = serving.promote(str(b), "second", serving_dir=self.sd)
        self.assertEqual(rec["previous"]["model_version"], "a-v")
        self.assertEqual(rec["validation_rule"], "passed")
        self.assertEqual(len((self.sd / "history.jsonl").read_text().splitlines()), 2)
        (self.sd / rec["checkpoint"]).write_bytes(b"tampered")
        with self.assertRaises(SystemExit):
            serving.resolve(serving_dir=self.sd)


if __name__ == "__main__":
    unittest.main()
