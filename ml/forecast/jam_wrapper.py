"""Jam-probability wrapper over a trained point forecaster (no retraining).

    python -m forecast jam-wrapper --checkpoint data/forecast/experiments/event_patch_v4_h18_full/best.pt

Maps the model's predicted congestion ratio to P(target congestion >= eval.buildup_congestion) with isotonic
regression per (cell group, horizon group), fitted on the validation event only; warning thresholds are also chosen
on validation and applied unchanged to test. Groups:
    antic  event run, issued within the longest lead band before public start/end, near road directly observed
           clear at issue time (the build-ups we want to warn about)
    near   other event-near cells of event runs
    other  everything else (control runs, far roads; subsampled)
The wrapper only re-reads the point forecast: it cannot recover a jam the model predicts as fully clear, it can only
move the warning threshold and report calibrated probabilities.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from . import config as cfg_mod
from . import event_windows as ew
from . import events as ev_mod
from .config import read_json, save_json
from .evaluate import derive
from .model import build_model
from .retrain import Prefetch, RetrainCfg, _index, forward_aux, jam_labels
from .train import Data, forward, load_checkpoint, pick_device, to_batch

GROUPS = ("antic", "near", "other")
HGROUPS = ((0, 60, "0-60"), (60, 120, "60-120"), (120, 180, "120-180"), (180, 240, "180-240"), (240, 300, "240-300"))


def _hgroup(h_min: np.ndarray) -> np.ndarray:
    out = np.empty(len(h_min), dtype=object)
    for lo, hi, name in HGROUPS:
        out[(h_min > lo) & (h_min <= hi)] = name
    return out


def collect(checkpoint: str, partition: str, near_frac: float = 0.3, other_frac: float = 0.01, seed: int = 0,
            log=None) -> pd.DataFrame:
    """Valid label cells of one partition: all antic cells, a `near_frac` sample of other near cells and an
    `other_frac` sample of the rest (sampling fixed by seed, independent of labels)."""
    log = log or (lambda m: print(m, flush=True))
    paths = str(checkpoint).split(",")        # several = ensemble (retrain.load_models)
    ck = load_checkpoint(paths[0])
    cfg = cfg_mod.from_dict(ck["config"])
    rc = RetrainCfg(**ck["retrain"]["retrain"])
    dev = pick_device(cfg)
    data = Data(cfg, dev)
    data.norm = ck["norm"]
    data.windows = data.windows[(data.windows.partition == partition) & (data.windows.ds == 0)].reset_index(drop=True)
    index, _ = _index(cfg, data, rc, counts=False)
    from .retrain import load_models
    model = load_models(paths, data.graph, dev)
    thr = cfg.eval.buildup_congestion
    rng = np.random.default_rng(seed)
    rows = index[index.partition == partition]
    nbs, parts = {}, []
    H = cfg.data.horizon_steps
    hmin = cfg.data.bucket_min * (np.arange(H) + 1)
    for k, (r, w) in enumerate(Prefetch(data, rows, list(rows.index), rc.prefetch)):
        if r.event_run not in nbs:
            nbs[r.event_run] = ew.neighbourhoods(data.run(r.event_run).context, data.graph, cfg)
        nb = nbs[r.event_run]
        b = to_batch(w, dev, data.event_tensors(r.run_id), cfg)
        with torch.no_grad():
            out = forward_aux(model, b, cfg.train.amp)
        z = out["z"][0].cpu().numpy()
        pc = derive(z, data.graph)["cong"]
        y_tol = jam_labels(b, thr, 2)[0].cpu().numpy() > 0.5     # jam within +-20 min (valid buckets)
        p_head = torch.sigmoid(out["jam_logit"])[0].cpu().numpy() if "jam_logit" in out else None
        if "z_q" in out:
            zq = out["z_q"][0].cpu().numpy()
            tz = np.nan_to_num(w.target_z)
            q_in = (tz >= zq[..., 0]) & (tz <= zq[..., -1])
            q_w = zq[..., -1] - zq[..., 0]
        else:
            q_in = q_w = None
        m = w.target_mask
        grp = np.full(m.shape, 2, np.int8)                        # other
        if r.with_event:
            grp[:, nb.near] = 1                                    # near
            if r.pre_start or r.pre_end:
                clear = ew.clear_roads(data.run(r.run_id), int(r.origin)) & nb.near
                grp[:, clear] = 0                                  # antic
        keep = m & ((grp == 0) | ((grp == 1) & (rng.random(m.shape) < near_frac))
                    | ((grp == 2) & (rng.random(m.shape) < other_frac)))
        hi, ri = np.nonzero(keep)
        df = pd.DataFrame({"group": np.asarray(GROUPS)[grp[hi, ri]], "horizon_min": hmin[hi],
                           "pred_cong": pc[hi, ri].astype(np.float32),
                           "y": np.nan_to_num(w.cong[hi, ri], nan=0.0) >= thr, "y_tol": y_tol[hi, ri],
                           "lead_cat": r.lead_cat, "family_id": r.family_id})
        if p_head is not None:
            df["p_head"] = p_head[hi, ri].astype(np.float32)
        if q_in is not None:
            df["q_in"], df["q_width"] = q_in[hi, ri], q_w[hi, ri].astype(np.float32)
        parts.append(df)
        if k % 100 == 0:
            log(f"  collect {partition}: {k}/{len(rows)} windows")
    df = pd.concat(parts, ignore_index=True)
    df["hgroup"] = _hgroup(df.horizon_min.to_numpy())
    df.attrs["sampling"] = {"near_frac": near_frac, "other_frac": other_frac, "seed": seed}
    return df


def fit(cells: pd.DataFrame, min_pos: int = 20) -> dict:
    """Isotonic P(jam | predicted congestion) per (group, horizon group) + validation-chosen warning thresholds:
    f1 = max F1; recall70 = highest threshold reaching recall >= 0.7 (None if unreachable)."""
    from sklearn.isotonic import IsotonicRegression
    cal = {}
    for (g, hg), d in cells.groupby(["group", "hgroup"]):
        x, y = d.pred_cong.to_numpy(np.float64), d.y.to_numpy()
        if y.sum() < min_pos or (~y).sum() < min_pos:
            continue
        iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(x, y.astype(float))
        p = iso.predict(x)
        grid = np.unique(np.round(p, 4))
        best, rec70 = (None, -1.0), None
        for t in grid[grid > 0]:
            pred = p >= t
            tp = (pred & y).sum()
            prec, rec = tp / max(pred.sum(), 1), tp / max(y.sum(), 1)
            f1 = 2 * prec * rec / max(prec + rec, 1e-12)
            if f1 > best[1]:
                best = (float(t), float(f1))
            if rec >= 0.7:
                rec70 = float(t)
        cal[f"{g}|{hg}"] = {"x": iso.X_thresholds_.tolist(), "p": iso.y_thresholds_.tolist(),
                            "threshold_f1": best[0], "threshold_recall70": rec70,
                            "fit_labels": int(len(d)), "fit_positives": int(y.sum())}
        if "p_head" in d:
            for lab in ("y", "y_tol"):
                cal[f"{g}|{hg}"][f"head_threshold_f1_{lab}"] = _best_f1(d.p_head.to_numpy(), d[lab].to_numpy())
    return cal


def _best_f1(p: np.ndarray, y: np.ndarray) -> float | None:
    if y.sum() == 0:
        return None
    best = (None, -1.0)
    for t in np.quantile(p, np.linspace(0.5, 0.999, 120)):
        pred = p >= t
        tp = (pred & y).sum()
        prec, rec = tp / max(pred.sum(), 1), tp / max(y.sum(), 1)
        f1 = 2 * prec * rec / max(prec + rec, 1e-12)
        if f1 > best[1]:
            best = (float(t), float(f1))
    return best[0]


def probability(cal: dict, group: str, hgroup: str, pred_cong: np.ndarray) -> np.ndarray | None:
    c = cal.get(f"{group}|{hgroup}")
    return None if c is None else np.interp(pred_cong, c["x"], c["p"])


def score(cells: pd.DataFrame, cal: dict, base_thr: float) -> pd.DataFrame:
    """Per (group, horizon group): base rule (predicted congestion >= threshold) vs calibrated warning thresholds."""
    out = []
    for (g, hg), d in cells.groupby(["group", "hgroup"]):
        y = d.y.to_numpy()
        row = {"group": g, "hgroup": hg, "labels": len(d), "positives": int(y.sum())}

        def pr(pred, tag):
            tp = int((pred & y).sum())
            p = tp / pred.sum() if pred.sum() else np.nan
            r = tp / y.sum() if y.sum() else np.nan
            row.update({f"{tag}_precision": p, f"{tag}_recall": r,
                        f"{tag}_f1": 2 * p * r / (p + r) if p and r and np.isfinite(p + r) else np.nan})
        pr(d.pred_cong.to_numpy() >= base_thr, "base")
        p = probability(cal, g, hg, d.pred_cong.to_numpy())
        if p is not None:
            c = cal[f"{g}|{hg}"]
            pr(p >= c["threshold_f1"], "f1thr")
            if c["threshold_recall70"] is not None:
                pr(p >= c["threshold_recall70"], "rec70thr")
            row["brier_calibrated"] = float(np.mean((p - y) ** 2))
            row["brier_base"] = float(np.mean(((d.pred_cong.to_numpy() >= base_thr).astype(float) - y) ** 2))
            row["mean_p"], row["jam_rate"] = float(p.mean()), float(y.mean())
        from sklearn.metrics import average_precision_score
        if 0 < y.sum() < len(y):
            row["ap_point"] = float(average_precision_score(y, d.pred_cong.to_numpy()))
        yt = d.y_tol.to_numpy() if "y_tol" in d else None
        if yt is not None:
            tp = int(((d.pred_cong.to_numpy() >= base_thr) & yt).sum())
            row["base_tol_precision"] = tp / max(int((d.pred_cong.to_numpy() >= base_thr).sum()), 1)
            row["tol_positives"] = int(yt.sum())
        if "p_head" in d:
            ph = d.p_head.to_numpy()
            c = cal.get(f"{g}|{hg}", {})
            if 0 < y.sum() < len(y):
                row["ap_head"] = float(average_precision_score(y, ph))
            row["brier_head"] = float(np.mean((ph - y) ** 2))
            if c.get("head_threshold_f1_y") is not None:
                pr(ph >= c["head_threshold_f1_y"], "head")
            if yt is not None and c.get("head_threshold_f1_y_tol") is not None:
                pred = ph >= c["head_threshold_f1_y_tol"]
                tp = int((pred & yt).sum())
                row["head_tol_precision"] = tp / max(int(pred.sum()), 1)
                row["head_tol_recall"] = tp / max(int(yt.sum()), 1)
        if "q_in" in d:
            row["q_coverage"], row["q_width_z"] = float(d.q_in.mean()), float(d.q_width.mean())
        out.append(row)
    return pd.DataFrame(out)


def run(checkpoint: str, out_dir: str | None = None, report: str | None = "reports/jam_wrapper_h18.md") -> dict:
    ck = load_checkpoint(str(checkpoint).split(",")[0])
    cfg = cfg_mod.from_dict(ck["config"])
    od = Path(out_dir) if out_dir else cfg.exp_dir / "jam_wrapper"
    od.mkdir(parents=True, exist_ok=True)
    cells = {}
    for part in ("val", "test"):   # collected predictions are cached next to the calibration
        f = od / f"cells_{part}.parquet"
        if f.exists():
            cells[part] = pd.read_parquet(f)
        else:
            cells[part] = collect(checkpoint, part)
            cells[part].to_parquet(f, index=False)
    val = cells["val"]
    val.attrs.setdefault("sampling", {"near_frac": 0.3, "other_frac": 0.01, "seed": 0})
    cal = fit(val)
    save_json(od / "calibration.json", {"checkpoint": str(checkpoint), "model_version": ck["model_version"],
                                        "fitted_on": "val (Bearrison) only", "jam": f"congestion >= {cfg.eval.buildup_congestion}",
                                        "sampling": val.attrs["sampling"], "groups": cal})
    res = {}
    for part in ("val", "test"):
        s = score(cells[part], cal, cfg.eval.buildup_congestion)
        s.to_csv(od / f"scores_{part}.csv", index=False)
        res[part] = s
    if report:
        _report(res, cfg, od, Path(cfg_mod.ML_DIR / report))
    return {"dir": str(od), **{p: s.to_dict("records") for p, s in res.items()}}


def _report(res: dict, cfg, od: Path, path: Path) -> None:
    from .finetune import _md
    cols = ["group", "hgroup", "labels", "positives", "base_precision", "base_recall", "base_f1", "f1thr_precision",
            "f1thr_recall", "f1thr_f1", "rec70thr_precision", "rec70thr_recall", "head_precision", "head_recall",
            "head_f1", "ap_point", "ap_head", "brier_base", "brier_calibrated", "brier_head", "head_tol_precision",
            "head_tol_recall", "q_coverage", "q_width_z"]
    L = ["# Jam-probability wrapper (3-hour model)", "",
         "> **Synthetic** SUMO data. Calibration and thresholds fitted on Bearrison (validation) only; Portola (test) "
         "uses them unchanged. Cells in `near`/`other` are subsampled (30% / 1%); `antic` is complete.", "",
         f"A jam = target congestion >= {cfg.eval.buildup_congestion}. `base` = the point forecast's own rule (predicted "
         "congestion >= threshold); `f1thr` = calibrated probability >= the F1-best validation threshold; `rec70thr` = "
         "the highest validation threshold that caught >= 70% of validation jams. `antic` = near roads observed clear at "
         "issue, forecast issued up to 3 h before public start/end.", ""]
    for part, label in (("val", "Bearrison (validation, fitted here)"), ("test", "Portola (held-out test)")):
        s = res[part]
        L += [f"## {label}", "", _md(s[[c for c in cols if c in s.columns]]), ""]
    L += ["## Reading this", "",
          "- The wrapper re-reads the point forecast. It can trade false alarms for caught jams, but a jam the model "
          "predicts as fully clear stays invisible; that needs retraining (see EVENT_ANTICIPATION_IMPROVEMENTS_PLAN.md).",
          f"- Calibration file: `{od / 'calibration.json'}` (isotonic knots per group x horizon group).", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L), encoding="utf-8")
