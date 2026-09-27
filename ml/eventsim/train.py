"""Stage 5: pooled gradient-boosted residual model (one model for all segments, horizon as a feature).

    python -m eventsim train --event castro

Fits on train families, picks hyper-parameters on validation families (test is not touched here), refits
nothing on validation. Saves ml/data/<event>/model/{model.pkl, model_card.json}.
Prediction: travel_time = clip(persistence_tt + model(features), physical bounds).
"""
from __future__ import annotations

import json
import os
import pickle
import platform
import time
from datetime import datetime, timezone

import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor

from .config import event_dir

from .features import FEATURES, Static, tt_bounds
from .simulate import Context

GRID = [
    {"learning_rate": 0.1, "max_leaf_nodes": 31, "max_iter": 300, "loss": "squared_error"},
    {"learning_rate": 0.05, "max_leaf_nodes": 63, "max_iter": 600, "loss": "squared_error"},
    {"learning_rate": 0.1, "max_leaf_nodes": 31, "max_iter": 300, "loss": "absolute_error"},
    {"learning_rate": 0.05, "max_leaf_nodes": 63, "max_iter": 600, "loss": "absolute_error"},
]
SEED = 0
Y_CLIP = 600.0  # residual targets beyond +-10 min per segment are clipped for fitting (rare gridlock tails)


def load_split(ev_key: str, split: str, max_rows: int | None = None, seed: int = 0) -> dict:
    d = event_dir(ev_key) / "dataset"
    sp = json.loads((d / "splits.json").read_text())
    parts = {k: [] for k in ("X", "y", "base_tt", "rule_tt", "true_tt", "seg", "t", "h", "run")}
    for rid, s in sorted(sp["runs"].items()):
        if s != split or not (d / f"{rid}.npz").exists():
            continue
        z = np.load(d / f"{rid}.npz")
        for k in parts:
            if k == "run":
                parts[k].append(np.full(len(z["y"]), rid, dtype=object))
            else:
                parts[k].append(z[k])
    out = {k: np.concatenate(v) for k, v in parts.items() if v}
    if max_rows and len(out["y"]) > max_rows:
        idx = np.random.default_rng(seed).choice(len(out["y"]), max_rows, replace=False)
        out = {k: v[idx] for k, v in out.items()}
    return out


class ResidualModel:
    """Wraps the regressor with the persistence baseline and physical bounds so predictions are reproducible."""

    def __init__(self, reg, bounds: tuple[np.ndarray, np.ndarray], meta: dict):
        self.reg, self.lo, self.hi, self.meta = reg, bounds[0], bounds[1], meta

    def predict_tt(self, X: np.ndarray, base_tt: np.ndarray, seg: np.ndarray) -> np.ndarray:
        return np.clip(base_tt + self.reg.predict(X), self.lo[seg], self.hi[seg])


def run(ev) -> dict:
    ctx = Context(ev.key)
    st = Static(ctx)
    bounds = tt_bounds(st)
    tr = load_split(ev.key, "train", max_rows=4_000_000)
    va = load_split(ev.key, "val")
    if "y" not in tr or "y" not in va:
        raise SystemExit("need train and val runs: run `dataset` first")
    results = []
    best = None
    for params in GRID:
        t0 = time.time()
        reg = HistGradientBoostingRegressor(**params, random_state=SEED, early_stopping=True, validation_fraction=0.1,
                                            n_iter_no_change=30, categorical_features=None)
        reg.fit(tr["X"], np.clip(tr["y"], -Y_CLIP, Y_CLIP))
        pred = np.clip(va["base_tt"] + reg.predict(va["X"]), bounds[0][va["seg"]], bounds[1][va["seg"]])
        mae = float(np.abs(pred - va["true_tt"]).mean())
        results.append({**params, "val_mae_s": round(mae, 4), "fit_s": round(time.time() - t0, 1),
                        "iters": int(reg.n_iter_)})
        print(results[-1], flush=True)
        if best is None or mae < best[0]:
            best = (mae, reg, params)
    mae, reg, params = best
    val_persist = float(np.abs(va["base_tt"] - va["true_tt"]).mean())
    val_rule = float(np.abs(va["rule_tt"] - va["true_tt"]).mean())
    sp = json.loads((event_dir(ev.key) / "dataset" / "splits.json").read_text())
    meta = {
        "model_version": f"eventsim-{ev.key}-hgb-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}",
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "event": ev.key, "features": FEATURES, "params": params, "seed": SEED, "grid": results,
        "train_rows": int(len(tr["y"])), "val_rows": int(len(va["y"])),
        "val_mae_s": {"learned": mae, "persistence": val_persist, "event_rule": val_rule},
        "families": sp["families"], "target_clip_s": Y_CLIP,
        "versions": {"python": platform.python_version(), "sklearn": sklearn.__version__, "numpy": np.__version__},
        "provenance": "trained on SUMO simulations grounded in a real permitted SF event and real roads; "
                      "not validated on measured event traffic",
    }
    mdir = event_dir(ev.key) / "model"
    mdir.mkdir(exist_ok=True)
    with open(mdir / "model.pkl", "wb") as f:
        pickle.dump(ResidualModel(reg, bounds, meta), f)
    (mdir / "model_card.json").write_text(json.dumps(meta, indent=1))
    return {"best": params, "val_mae_s": meta["val_mae_s"], "model": str(mdir / "model.pkl")}


def load_model(ev_key: str) -> ResidualModel:
    with open(event_dir(ev_key) / "model" / "model.pkl", "rb") as f:
        return pickle.load(f)
