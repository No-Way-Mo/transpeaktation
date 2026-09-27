"""Held-out evaluation: persistence vs the patch model (with / without event conditioning) on identical labels.

Metrics are accumulated per (run, horizon, event-near, severe) cell so every marginal in the report is computed from
the same rows. Travel time in seconds, speed in mph, congestion ratio, and the transformed z loss. Build-up detection
uses thresholds declared in the config before evaluation. Road/time rows are NOT independent samples: the unit of
generalisation is the event group (one test group in the primary split), so per-event results are reported beside
pooled numbers.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from scipy.spatial import cKDTree

from . import config as cfg_mod
from . import events as ev_mod
from .config import MPH_PER_MPS, SPEED_FLOOR_MPS, read_json, save_json
from .data import persistence_z
from .model import build_model
from .train import Data, forward, load_checkpoint, pick_device, to_batch

Z_MIN = -1.0   # predicted speed <= e * free flow


def z_bounds(graph) -> tuple[float, np.ndarray]:
    """Upper bound = the export's 0.1 m/s speed floor, so severe congestion is kept (not clipped into ordinary)."""
    zmax = np.log((graph.free_flow_mph / MPH_PER_MPS) / SPEED_FLOOR_MPS)
    return Z_MIN, zmax.astype(np.float32)


def derive(z: np.ndarray, graph) -> dict:
    """z [..., N] -> mutually consistent travel time (s), speed (mph), congestion ratio."""
    lo, hi = z_bounds(graph)
    zc = np.clip(z, lo, hi)
    tt = graph.ref_tt_s * np.exp(zc)
    speed = graph.length_m / tt * MPH_PER_MPS
    cong = np.clip(1 - speed / graph.free_flow_mph, 0, 1)
    return {"tt": tt, "speed": speed, "cong": cong, "z": zc}


def near_mask(ctx: dict, graph, radius: float) -> np.ndarray:
    fp = ev_mod.focal_footprint(ctx, graph)
    if not len(fp):
        return np.zeros(graph.n, bool)
    return cKDTree(graph.xy[fp]).query(graph.xy)[0] <= radius


class Acc:
    """Sums per (system, run, horizon, near, severe) plus build-up confusion counts."""

    def __init__(self):
        self.rows = []

    def add(self, system, run_id, pred, tgt, mask, near, prior_cong, cfg):
        H = mask.shape[0]
        severe = tgt["cong"] >= cfg.eval.buildup_congestion
        elig = ~(prior_cong >= cfg.eval.buildup_prior_max)             # prior < 0.3 or missing
        for h in range(H):
            m = mask[h]
            for nv in (True, False):
                for sv in (True, False):
                    c = m & (near == nv) & (severe[h] == sv)
                    n = int(c.sum())
                    if not n:
                        continue
                    e = lambda k: float(np.abs(pred[k][h][c] - tgt[k][h][c]).sum())
                    act = severe[h][c & elig]
                    prd = pred["cong"][h][c & elig] >= cfg.eval.buildup_congestion
                    self.rows.append({"system": system, "run_id": run_id, "horizon_min": 10 * (h + 1), "near": nv,
                                      "severe": sv, "n": n, "tt_ae": e("tt"), "speed_ae": e("speed"),
                                      "cong_ae": e("cong"), "z_ae": e("z"), "tt_true": float(tgt["tt"][h][c].sum()),
                                      "bu_tp": int((act & prd).sum()), "bu_fp": int((~act & prd).sum()),
                                      "bu_fn": int((act & ~prd).sum()), "bu_tn": int((~act & ~prd).sum())})

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows)


def summarize(df: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    g = df.groupby(by, dropna=False)[["n", "tt_ae", "speed_ae", "cong_ae", "z_ae", "tt_true", "bu_tp", "bu_fp",
                                        "bu_fn", "bu_tn"]].sum()
    out = pd.DataFrame({"labels": g.n, "tt_mae_s": g.tt_ae / g.n, "speed_mae_mph": g.speed_ae / g.n,
                        "cong_mae": g.cong_ae / g.n, "z_mae": g.z_ae / g.n, "tt_wape": g.tt_ae / g.tt_true})
    p = g.bu_tp / (g.bu_tp + g.bu_fp).replace(0, np.nan)
    r = g.bu_tp / (g.bu_tp + g.bu_fn).replace(0, np.nan)
    out["buildup_precision"], out["buildup_recall"] = p, r
    out["buildup_f1"] = 2 * p * r / (p + r)
    out["buildup_positives"] = g.bu_tp + g.bu_fn
    return out.reset_index()


@torch.no_grad()
def evaluate(checkpoint: str, partition: str = "test") -> dict:
    ck = load_checkpoint(checkpoint)
    cfg = cfg_mod.from_dict(ck["config"])
    dev = pick_device(cfg)
    data = Data(cfg, dev)
    if ck["dataset_manifest_sha256"] != data.manifest_sha or ck["splits_sha256"] != data.splits_sha:
        raise SystemExit("checkpoint was trained on a different dataset manifest / split")
    g = data.graph
    if list(map(str, g.model_ids)) != ck["model_ids"]:
        raise SystemExit("road order differs from the checkpoint")
    model = build_model(cfg, g, ck["norm"], len(ev_mod.EVENT_PAIR_FEATURES)).to(dev)
    model.load_state_dict(ck["model"])
    model.eval()
    rows = data.partition(partition)
    wins = read_json(cfg.dataset_dir / "manifest.json")["selected_runs"]
    fam_event_run = {r["family_id"]: r["run_id"] for r in wins if r["with_event"]}
    acc = Acc()
    per_window, cf_rows = [], []
    lat, cov = [], {"windows": 0, "cells": 0, "labels": 0, "not_observed": 0, "closed": 0}
    if dev.type == "cuda":
        torch.cuda.reset_peak_memory_stats()
    near_cache = {}
    for r in rows.itertuples():
        a = data.run(r.run_id)
        w = data.window(r)
        ev = data.event_tensors(r.run_id) if cfg.model.use_events else None
        if dev.type == "cuda":
            torch.cuda.synchronize()
        t0 = time.time()
        z = forward(model, to_batch(w, dev, ev, cfg), cfg.train.amp)[0].cpu().numpy()
        if dev.type == "cuda":
            torch.cuda.synchronize()
        lat.append(time.time() - t0)
        if r.family_id not in near_cache:
            near_cache[r.family_id] = near_mask(data.run(fam_event_run[r.family_id]).context, g, cfg.events.near_radius_m)
        near = near_cache[r.family_id]
        m = w.target_mask
        tgt = {"tt": w.tt, "speed": w.speed, "cong": w.cong, "z": np.nan_to_num(w.target_z)}
        prior = np.clip(1 - np.exp(-w.zf_last), 0, 1)                   # NaN where history missing after fill
        systems = {"persistence": np.broadcast_to(persistence_z(w.zf_last), m.shape), "model": z}
        for s, zs in systems.items():
            pred = derive(zs, g)
            acc.add(s, r.run_id, pred, tgt, m, near, prior, cfg)
            per_window.append({"system": s, "run_id": r.run_id, "issued_at": r.issued_at, "labels": int(m.sum()),
                               "tt_mae_s": float(np.abs(pred["tt"] - tgt["tt"])[m].mean()),
                               "z_mae": float(np.abs(pred["z"] - tgt["z"])[m].mean())})
        if cfg.model.use_events and r.with_event:   # counterfactual: drop the focal event from the context
            ctx = json.loads(json.dumps(a.context))
            ctx["cases"] = [c for c in ctx["cases"] if c["kind"] != "public_event"]
            z0 = forward(model, to_batch(w, dev, data.event_tensors(r.run_id, context=ctx), cfg),
                         cfg.train.amp)[0].cpu().numpy()
            p0 = derive(z0, g)
            for nv in (True, False):
                mm = m & (near == nv)
                cf_rows.append({"run_id": r.run_id, "issued_at": r.issued_at, "near": nv, "n": int(mm.sum()),
                                "mean_abs_dz": float(np.abs(z0 - z)[mm].mean()) if mm.any() else np.nan,
                                "mean_dz": float((z - z0)[mm].mean()) if mm.any() else np.nan,
                                "tt_mae_with_event": float(np.abs(derive(z, g)["tt"] - tgt["tt"])[mm].mean()) if mm.any() else np.nan,
                                "tt_mae_without_event": float(np.abs(p0["tt"] - tgt["tt"])[mm].mean()) if mm.any() else np.nan})
        cov["windows"] += 1
        cov["cells"] += m.size
        cov["labels"] += int(m.sum())
        ob = np.asarray(a.obs[w.origin:w.origin + cfg.data.horizon_steps])
        cl = np.asarray(a.closed[w.origin:w.origin + cfg.data.horizon_steps])
        cov["not_observed"] += int((~ob).sum())
        cov["closed"] += int(cl.sum())
    df = acc.frame()
    out = cfg.exp_dir / f"eval_{partition}"
    out.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out / "cells.parquet", index=False)
    pd.DataFrame(per_window).to_csv(out / "per_window.csv", index=False)
    if cf_rows:
        pd.DataFrame(cf_rows).to_csv(out / "counterfactual_no_focal_event.csv", index=False)
    cov["not_modelled_roads_per_bucket"] = int(len(g.roads) - g.n)
    res = {"checkpoint": str(checkpoint), "experiment": cfg.name, "model_version": ck["model_version"],
           "best_epoch": ck["state"]["best_epoch"], "partition": partition, "coverage": cov,
           "latency_s_per_city_window": {"mean": float(np.mean(lat[1:] or lat)), "max": float(np.max(lat))},
           "peak_gpu_mb": round(torch.cuda.max_memory_allocated() / 2**20, 1) if dev.type == "cuda" else None,
           "device": str(dev),
           "overall": summarize(df, ["system"]).to_dict("records")}
    save_json(out / "summary.json", res)
    return res


# ---------------------------------------------------------------- report

def _fmt(df: pd.DataFrame, cols: list[str]) -> str:
    def f(v):
        if isinstance(v, (bool, np.bool_)):
            return "yes" if v else "no"
        if isinstance(v, (float, np.floating)):
            return "–" if not np.isfinite(v) else (f"{v:.3f}" if abs(v) < 10 else f"{v:.1f}")
        return str(v)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(f(v) for v in row) + " |" for row in df[cols].itertuples(index=False)]
    return "\n".join(lines)


def load_cells(cfg, exp: str, partition: str) -> pd.DataFrame:
    d = cfg.path(cfg.data.out_root) / "experiments" / exp / f"eval_{partition}"
    df = pd.read_parquet(d / "cells.parquet")
    df.loc[df.system == "model", "system"] = exp
    return df


def plot_curves(root: Path, experiments: list[str], path: Path) -> None:
    """Small multiples (one panel per experiment, shared y): train vs validation loss per epoch."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ink, muted, grid, base = "#0b0b0b", "#898781", "#e1e0d9", "#c3c2b7"
    colors = {"train_loss": "#2a78d6", "val_loss": "#eb6834"}          # categorical slots 1, 2 (validated pair)
    fig, axes = plt.subplots(1, len(experiments), figsize=(4.6 * len(experiments), 3.4), sharey=True,
                             facecolor="#fcfcfb")
    axes = np.atleast_1d(axes)
    for ax, e in zip(axes, experiments):
        c = pd.read_csv(root / e / "curves.csv")
        best = read_json(root / e / "train_summary.json")["best_epoch"]
        ax.set_facecolor("#fcfcfb")
        for k, lab in (("train_loss", "train"), ("val_loss", "validation")):
            ax.plot(c.epoch, c[k], color=colors[k], lw=2, label=lab, marker="o", ms=3)
            ax.annotate(lab, (c.epoch.iloc[-1], c[k].iloc[-1]), xytext=(4, 0), textcoords="offset points",
                        va="center", fontsize=8, color=ink)
        ax.axvline(best, color=muted, lw=1, ls=(0, (2, 2)))
        ax.annotate(f"best epoch {best}", (best, ax.get_ylim()[1]), xytext=(3, -10), textcoords="offset points",
                    fontsize=8, color=muted)
        ax.set_title(e, fontsize=10, color=ink, loc="left")
        ax.set_xlabel("epoch", fontsize=9, color=muted)
        ax.grid(axis="y", color=grid, lw=0.6)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            ax.spines[s].set_color(base)
        ax.tick_params(colors=muted, labelsize=8)
    axes[0].set_ylabel("masked Huber loss on z", fontsize=9, color=muted)
    axes[0].legend(frameon=False, fontsize=8, labelcolor=ink)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def report(cfg, experiments: list[str]) -> dict:
    """Markdown report comparing persistence and each experiment on the frozen val/test partitions."""
    from .data import HIST_FEATURES
    root = cfg.path(cfg.data.out_root) / "experiments"
    man = read_json(cfg.dataset_dir / "manifest.json")
    splits = read_json(cfg.dataset_dir / "splits.json")
    runs = {r["run_id"]: r for r in man["selected_runs"]}
    lines = [f"# Forecast experiment report: {', '.join(experiments)}", "",
             "> **Synthetic.** Trained and evaluated on SUMO scenarios (`sumo_synthetic`) grounded in real SF roads and "
             "permits. Demand, attendance and behaviour are scenario assumptions. None of these numbers are "
             "validated against measured traffic.", ""]
    res = {}
    png = cfg.path("reports") / f"forecast_{experiments[0]}_curves.png"
    plot_curves(root, experiments, png)
    ts = pd.DataFrame([{"experiment": e, **read_json(root / e / "train_summary.json")} for e in experiments])
    lines += ["## Training", "", f"![training curves]({png.name})", "",
              _fmt(ts, ["experiment", "best_epoch", "best_val_loss", "epochs_run", "early_stopped", "train_seconds",
                        "peak_gpu_mb", "parameters"]), ""]
    res["training"] = ts.to_dict("records")
    for part in ("val", "test"):
        cells = []
        for i, e in enumerate(experiments):
            c = load_cells(cfg, e, part)
            if i:
                c = c[c.system != "persistence"]
            cells.append(c)
        df = pd.concat(cells)
        df["with_event"] = df.run_id.map(lambda r: runs[r]["with_event"])
        df["group"] = df.run_id.map(lambda r: runs[r]["family_group"])
        systems = ["persistence"] + experiments
        order = {s: i for i, s in enumerate(systems)}
        srt = lambda x: x.sort_values(by=[c for c in x.columns if c in ("group", "with_event", "near", "severe",
                                                                          "horizon_min")] + ["system"],
                                      key=lambda s: s.map(order) if s.name == "system" else s)
        lines += [f"## {part.upper()} partition: {', '.join(splits[part])}", ""]
        overall = summarize(df, ["system"]).sort_values("system", key=lambda s: s.map(order))
        res[part] = {"overall": overall.to_dict("records")}
        cols = ["system", "labels", "tt_mae_s", "tt_wape", "speed_mae_mph", "cong_mae", "z_mae"]
        lines += ["### All labelled road-buckets (horizons pooled, equal weight per label)", "", _fmt(overall, cols), ""]
        hz = srt(summarize(df, ["horizon_min", "system"]))
        lines += ["### By horizon", "", _fmt(hz, ["horizon_min"] + cols), ""]
        res[part]["by_horizon"] = hz.to_dict("records")
        ev = srt(summarize(df, ["with_event", "system"]))
        lines += ["### Event vs control run", "", _fmt(ev, ["with_event"] + cols), ""]
        res[part]["event_vs_control"] = ev.to_dict("records")
        nr = srt(summarize(df, ["with_event", "near", "system"]))
        lines += [f"### Event-near (≤ {cfg.events.near_radius_m:.0f} m of the focal footprint) vs other roads", "",
                  _fmt(nr, ["with_event", "near"] + cols), ""]
        res[part]["near"] = nr.to_dict("records")
        hn = srt(summarize(df[df.near & df.with_event], ["horizon_min", "system"]))
        lines += ["### Event run, event-near roads, by horizon", "", _fmt(hn, ["horizon_min"] + cols), ""]
        res[part]["event_near_by_horizon"] = hn.to_dict("records")
        sv = srt(summarize(df, ["severe", "system"]))
        lines += [f"### Severe targets (congestion ≥ {cfg.eval.buildup_congestion}) vs others", "",
                  _fmt(sv, ["severe"] + cols), ""]
        res[part]["severe"] = sv.to_dict("records")
        pe = srt(summarize(df, ["group", "with_event", "system"]))
        lines += ["### Per event group and run type", "", _fmt(pe, ["group", "with_event"] + cols), ""]
        per_group = summarize(df, ["group", "system"])
        macro = per_group.groupby("system")[["tt_mae_s", "speed_mae_mph", "cong_mae", "z_mae"]].mean().reset_index()
        macro = macro.sort_values("system", key=lambda s: s.map(order))
        lines += [f"Macro-average over {df.group.nunique()} event group(s):", "",
                  _fmt(macro, ["system", "tt_mae_s", "speed_mae_mph", "cong_mae", "z_mae"]), ""]
        res[part]["macro"] = macro.to_dict("records")
        bu = srt(summarize(df, ["horizon_min", "system"]))
        lines += [f"### Congestion build-up detection (declared: target congestion ≥ {cfg.eval.buildup_congestion} "
                  f"on a road whose issue-time value was < {cfg.eval.buildup_prior_max} or missing)", "",
                  _fmt(bu, ["horizon_min", "system", "buildup_positives", "buildup_precision", "buildup_recall",
                            "buildup_f1"]), ""]
        res[part]["buildup"] = bu.to_dict("records")
        for e in experiments:
            s = read_json(root / e / f"eval_{part}" / "summary.json")
            res[part].setdefault("runtime", {})[e] = {k: s[k] for k in ("latency_s_per_city_window", "peak_gpu_mb",
                                                                         "device", "best_epoch", "model_version")}
            res[part]["coverage"] = s["coverage"]
        cov = res[part]["coverage"]
        lines += ["### Coverage", "",
                  f"- windows: {cov['windows']}; target cells (modelled roads × horizons): {cov['cells']:,}",
                  f"- valid labels: {cov['labels']:,} ({cov['labels'] / cov['cells']:.1%}); excluded: not observed "
                  f"{cov['not_observed']:,}, closed {cov['closed']:,} (closures are routing restrictions, not labels)",
                  f"- roads not modelled (no SUMO edge / merged parallel / no passenger access): "
                  f"{cov['not_modelled_roads_per_bucket']} per bucket, never labelled", ""]
        for e in experiments:
            rt = res[part]["runtime"][e]
            lines.append(f"- `{e}` (best epoch {rt['best_epoch']}): full-city inference "
                         f"{rt['latency_s_per_city_window']['mean'] * 1000:.0f} ms/window on {rt['device']}, "
                         f"peak GPU {rt['peak_gpu_mb']} MB")
        lines.append("")
        pw = []
        for e in experiments:
            p = pd.read_csv(root / e / f"eval_{part}" / "per_window.csv")
            p = p[p.system == "model"].assign(system=e)
            pw.append(p)
        pw.append(pd.read_csv(root / experiments[0] / f"eval_{part}" / "per_window.csv").query("system == 'persistence'"))
        pw = pd.concat(pw).pivot_table(index=["run_id", "issued_at"], columns="system", values="tt_mae_s")
        res[part]["per_window_wins"] = {}
        if len(experiments) >= 2:
            a, b = experiments[0], experiments[1]
            wins = int((pw[a] < pw[b]).sum())
            res[part]["per_window_wins"][f"{a}_beats_{b}"] = f"{wins}/{len(pw)}"
            lines += [f"Per-window travel-time MAE: `{a}` lower than `{b}` in {wins}/{len(pw)} windows "
                      "(windows overlap in time and share runs; not independent trials).", ""]
        for e in experiments:
            wins = int((pw[e] < pw["persistence"]).sum())
            res[part]["per_window_wins"][f"{e}_beats_persistence"] = f"{wins}/{len(pw)}"
            lines.append(f"`{e}` lower than persistence in {wins}/{len(pw)} windows.")
        lines.append("")
        cfp = root / experiments[0] / f"eval_{part}" / "counterfactual_no_focal_event.csv"
        if cfp.exists():
            cf = pd.read_csv(cfp).query("n > 0")
            t = cf.groupby("near").apply(lambda x: pd.Series({
                "labels": x.n.sum(), "mean_abs_dz": np.average(x.mean_abs_dz, weights=x.n),
                "mean_dz_event_minus_none": np.average(x.mean_dz, weights=x.n),
                "tt_mae_with_event": np.average(x.tt_mae_with_event, weights=x.n),
                "tt_mae_focal_event_removed": np.average(x.tt_mae_without_event, weights=x.n)})).reset_index()
            lines += [f"### Counterfactual: `{experiments[0]}` on event runs with the focal event removed from its "
                      "context (traffic inputs unchanged)", "",
                      _fmt(t, list(t.columns)), ""]
            res[part]["counterfactual"] = t.to_dict("records")
    path = cfg.path("reports") / f"forecast_{experiments[0]}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    save_json(root / experiments[0] / "report.json", res)
    return {"report": str(path)}
