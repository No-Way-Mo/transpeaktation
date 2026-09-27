"""Load-balancing backtest (LOAD_BALANCING_BACKTEST_PLAN.md §6-§7, §11): does coordinated route selection reduce
total travel time and congestion versus independent forecast-based routing in matched closed-loop SUMO replays?

    python -m coordination backtest --config configs/coordinated_routing_backtest.yaml --phase dev|heldout|report|all

Phases (every run a separate, resumable experiment id; see runner.py):

* dev (validation split, development scenarios x `benchmark.seeds`), one process pool:
  - profile/sanity: one scenario x seed 0: forecast_only twice (repeatability), heuristic@lam=0 (must reproduce
    independent routing), heuristic, batch;
  - screening at the base participation: forecast_only, heuristic (lam 60, 15, 120), batch (60 s and 15 s windows),
    heuristic@w=60 (equal-timing control for batch);
  - adoption: forecast_only / heuristic / batch at 15% and 30% participation;
  - compliance: the same three at 15% participation with 75% and 50% compliance.
* heldout (test split, one scenario per family, `HELDOUT_SEEDS`), a FIXED matrix declared before any run so it can
  run in parallel with dev on another node: forecast_only + every held-out candidate (`HELDOUT[p]`) at 5% and 30%
  participation.
* selection (pre-declared here, applied to dev results only, frozen to selection_<id>.json before the held-out
  results are read): best = the eligible held-out candidate (every screening run strictly complete) with the lowest
  mean paired vehicle-hours vs forecast_only on common complete screening blocks; challenger = the best eligible
  candidate of the other family (heuristic vs batch). The final report headlines only best and challenger on held-out;
  the other held-out candidates are listed separately and never used to pick a winner.
* report: reports/load_balancing_backtest_<backtest id>.md with every experiment's report linked.

RL policies are not part of this matrix unless listed in `--rl` with trained, compatible checkpoints.
"""
from __future__ import annotations

import copy
import hashlib
import json
import time
from pathlib import Path

import pandas as pd

from ..config import Config
from . import report, runner

SCREEN = ["forecast_only", "heuristic", "heuristic@lam=15", "heuristic@lam=120", "batch", "batch@w=15",
          "heuristic@w=60"]
CORE = ["forecast_only", "heuristic", "batch"]
PROFILE = ["forecast_only", "forecast_only@rep=1", "heuristic@lam=0", "heuristic", "batch"]
ADOPTION = [0.15, 0.30]
COMPLIANCE_AT = 0.15
COMPLIANCE = [0.75, 0.5]
HELDOUT_SEEDS = [0, 1, 2]
CANDIDATES = ["heuristic", "heuristic@lam=120", "batch"]           # policies the selection may choose
HELDOUT = {0.05: ["forecast_only", *CANDIDATES], 0.30: CORE}


def variant(cfg: Config, participation: float | None = None, compliance: float | None = None) -> Config:
    c = copy.deepcopy(cfg)
    if participation is not None:
        c.env.participation = participation
    if compliance is not None:
        c.env.compliance = compliance
    c.name = f"{cfg.name}_p{round(100 * c.env.participation)}_c{round(100 * c.env.compliance)}"
    return c


def dev_experiments(cfg: Config) -> dict:
    scen = runner.choose_scenarios(cfg, "screening")
    seeds = list(cfg.benchmark.seeds)
    E = {"profile": runner.prepare(variant(cfg), "profile", PROFILE, scen[:1], [0]),
         "screen": runner.prepare(variant(cfg), "screening", SCREEN, scen, seeds)}
    for p in ADOPTION:
        E[f"adopt_{round(100 * p)}"] = runner.prepare(variant(cfg, p), "screening", CORE, scen, seeds)
    for c in COMPLIANCE:
        E[f"comply_{round(100 * c)}"] = runner.prepare(variant(cfg, COMPLIANCE_AT, c), "screening", CORE, scen, seeds)
    return E


def _family(policy: str) -> str:
    return runner.parse_policy(policy)[0]


def select(dev: dict) -> dict:
    """The pre-declared rule (module docstring). Input: {name: results} of the dev phase only."""
    S = report.summarize(dev["screen"])
    rank = [r for r in S["ranking"] if r["policy"] in CANDIDATES and r["policy"] in S["eligible"]]
    note = []
    if rank:
        best = rank[0]["policy"]
        other = [r["policy"] for r in rank if _family(r["policy"]) != _family(best)]
        challenger = other[0] if other else next((r["policy"] for r in rank[1:]), None)
    else:
        best, challenger = "heuristic", "batch"
        note.append("no eligible held-out candidate on the screening blocks: default heuristic/batch are headlined "
                    "so the negative result is tested, not hidden")
    adoption = {}
    for name, res in dev.items():
        if name == "screen" or name.startswith("adopt_"):
            pv = report.summarize(res)["paired"]
            for fam in ("heuristic", "batch"):
                r = pv[(pv.policy == fam) & (pv.metric == "vehicle_hours")] if not pv.empty else pv
                adoption.setdefault(fam, {})[str(res["meta"]["participation"])] = \
                    float(r.mean_rel_pct.iloc[0]) if len(r) else None
    return {"best": best, "challenger": challenger, "candidates": CANDIDATES, "screen_ranking": S["ranking"],
            "eligible": S["eligible"], "dev_adoption_mean_rel_pct": adoption, "notes": note,
            "rule": "best = lowest mean paired vehicle-hours among strictly complete held-out candidates on common "
                    "complete screening blocks; challenger = best candidate of the other family; decided from dev "
                    "results only",
            "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def heldout_experiments(cfg: Config, rl: list | None = None) -> dict:
    scen = runner.choose_scenarios(cfg, "heldout")
    return {f"heldout_{round(100 * p)}": runner.prepare(variant(cfg, p), "heldout", [*pols, *(rl or [])], scen,
                                                         HELDOUT_SEEDS)
            for p, pols in HELDOUT.items()}


def _write_reports(cfg: Config, name: str, res: dict) -> dict:
    out = cfg.path(cfg.benchmark.out_dir) / res["meta"]["experiment_id"]
    rep = report.write(res, out / "report.md", out / "runs.csv")
    md = cfg.path("reports") / f"coordination_benchmark_{res['meta']['experiment_id']}.md"
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text((out / "report.md").read_text(encoding="utf-8"), encoding="utf-8")
    return {**rep, "name": name, "report": str(md)}


def _pv_rows(res: dict, policies: list, metrics=("vehicle_hours", "congested_h_scope", "congested_h_all",
                                                  "other_trip_s_mean", "part_trip_s_p95")) -> list:
    S = report.summarize(res)
    pv = S["paired"]
    rows = []
    for p in policies:
        row = {"policy": p, "blocks": len(S["blocks"])}
        for m in metrics:
            r = pv[(pv.policy == p) & (pv.metric == m)] if not pv.empty else pv
            row[f"{m} %"] = float(r.mean_rel_pct.iloc[0]) if len(r) else None
            if m == "vehicle_hours" and len(r):
                row["veh-h diff"] = float(r.mean_diff.iloc[0])
                row["better/worse"] = f"{int(r.better.iloc[0])}/{int(r.worse.iloc[0])}"
        rows.append(row)
    return rows


def _mechanism(named: dict) -> list:
    """How much each policy actually changes routes (diversions), per experiment."""
    mech = []
    for name, res in named.items():
        df = report.flatten(res)
        df = df[df.status == "ok"]
        for pol, g in df.groupby("policy"):
            if pol in ("forecast_only", "heuristic", "heuristic@lam=120", "batch"):
                mech.append({"experiment": name, "policy": pol, "participants / in-scope":
                             round(g.participants.mean() / g.in_scope_vehicles.mean(), 4),
                             "single-option share": round(g.trivial.mean() / g.participants.mean(), 3),
                             "non-fastest share of decided": round(g.non_fastest_share.mean(), 3),
                             "predicted extra s per decision": round(g.forecast_extra_travel_s_mean.mean(), 3),
                             "batch wait s": round(g.batch_delay_s_mean.mean(), 1),
                             "congested share of vehicle time": round((g.congested_h_scope / g.vehicle_hours).mean(), 3),
                             "episode wall s": round(g.wall_s.mean())})
    return mech


def final_report(cfg: Config, backtest_id: str, dev: dict, sel: dict | None, held: dict, reps: dict) -> Path:
    L = [f"# Load-balancing backtest `{backtest_id}`", "",
         "> **Synthetic.** Closed-loop SUMO replays of SF event scenarios; demand, attendance, participation and "
         "compliance are assumptions. Results support claims about these simulated scenarios, not observed SF "
         "outcomes.", "",
         "Question: with the same scheduled trips, event, road network and background traffic, does coordinated route "
         "selection reduce total travel burden and time in congested traffic versus independent forecast-based "
         "routing (`forecast_only`)?", "",
         "Percentages below are mean paired changes vs `forecast_only` over common complete blocks (negative = less "
         "time/congestion = better). congested = vehicle-hours at speed <= 50% of free-flow on mapped roads.", ""]
    if "profile" in dev:
        df = report.flatten(dev["profile"])
        vh = df.set_index("policy").vehicle_hours
        L += ["## Phase 0: sanity and repeatability (one development block)", "",
              report._md(df[["policy", "status", "complete", "vehicle_hours", "congested_h_scope", "decided",
                             "non_fastest_share", "teleports", "unfinished", "wall_s", "peak_mem_mb"]], index=False), ""]
        if {"forecast_only", "forecast_only@rep=1"} <= set(vh.index):
            d = vh["forecast_only@rep=1"] - vh["forecast_only"]
            L.append(f"- Repeatability: same policy twice differs by {d:+.4f} veh-h "
                     f"({100 * d / vh['forecast_only']:+.4f}%). Differences between policies smaller than this are noise.")
        if {"forecast_only", "heuristic@lam=0"} <= set(vh.index):
            d = vh["heuristic@lam=0"] - vh["forecast_only"]
            L.append(f"- lam=0 sanity: heuristic without the load penalty vs forecast_only differs by {d:+.4f} veh-h "
                     "(expected ~0 up to tie-breaking).")
        L.append("")
    if "screen" in dev:
        L += ["## Phase 1: screening at the base participation (validation split)", "",
              report._md(pd.DataFrame(_pv_rows(dev["screen"], [p for p in SCREEN if p != "forecast_only"])),
                         index=False), "",
              "`heuristic@w=60` is the equal-timing control for `batch` (same 60 s release groups, sequential "
              "heuristic): batch minus it isolates joint optimisation from batching delay.", ""]
    ad = [(dev[k]["meta"]["participation"], dev[k]) for k in ["screen"] + [f"adopt_{round(100 * p)}" for p in ADOPTION]
          if k in dev]
    if ad:
        rows = []
        for p, res in ad:
            mf = cfg.path(cfg.benchmark.out_dir) / res["meta"]["experiment_id"] / "manifest.json"
            cohorts = json.loads(mf.read_text()).get("cohorts", []) if mf.exists() else []
            share = sum(c["participants"] for c in cohorts) / sum(c["in_scope"] for c in cohorts) if cohorts else None
            for r in _pv_rows(res, ["heuristic", "batch"]):
                rows.append({"participation (of eligible)": p, "participants / in-scope": share and round(share, 4), **r})
        L += ["## Phase 2a: adoption (heuristic and batch vs forecast_only)", "", report._md(pd.DataFrame(rows),
                                                                                             index=False), ""]
    cp = [(dev[k]["meta"]["compliance"], dev[k]) for k in [f"comply_{round(100 * c)}" for c in COMPLIANCE] if k in dev]
    if cp:
        rows = [{"compliance": c, **r} for c, res in cp for r in _pv_rows(res, ["heuristic", "batch"])]
        L += [f"## Phase 2b: compliance at {COMPLIANCE_AT:.0%} participation", "",
              report._md(pd.DataFrame(rows), index=False), ""]
    if sel:
        L += ["## Frozen selection (from development data only)", "", "```json",
              json.dumps({k: v for k, v in sel.items() if k != "screen_ranking"}, indent=1, default=str), "```", ""]
    verdict = []
    head = [p for p in (sel.get("best"), sel.get("challenger")) if p] if sel else []
    for name, res in held.items():
        pols = [p for p in res["meta"]["policies"] if p != "forecast_only"]
        S = report.summarize(res)
        shown = [p for p in pols if p in head] if head else []
        rest = [p for p in pols if p not in shown]
        L += [f"## Phase 3: held-out ({res['meta']['participation']:.0%} participation, test split, "
              f"{len(res['meta']['scenarios'])} scenario families x seeds {res['meta']['seeds']})", ""]
        if shown:
            L += ["Selected on development data (best, challenger):", "",
                  report._md(pd.DataFrame(_pv_rows(res, shown)), index=False), "", "Development targets:", "",
                  "```json", json.dumps({p: S["targets"].get(p) for p in shown}, indent=1, default=str), "```", ""]
        elif not sel:
            L += ["(no frozen selection yet: development results missing; nothing is headlined)", ""]
        if rest:
            L += ["Other pre-declared held-out candidates (not selected; listed for completeness, never used to pick "
                  "a winner):", "", report._md(pd.DataFrame(_pv_rows(res, rest)), index=False), ""]
        for p in shown:
            verdict.append({"heldout": name, "policy": p, **(S["targets"].get(p) or {})})
    if not dev or not held:
        L += [f"> **Partial report:** development results {'present' if dev else 'MISSING'}, held-out results "
              f"{'present' if held else 'MISSING'}.", ""]
    mech = _mechanism({**{k: v for k, v in dev.items() if k in ("screen", "adopt_30")}, **held})
    if mech:
        L += ["## Mechanism: how much the coordinator actually changes", "",
              "`forecast_only` also shows a small non-fastest share (near-ties broken by the seeded hash). A policy "
              "can only move congestion through the drivers it diverts; compare its non-fastest share with the "
              "baseline's.", "", report._md(pd.DataFrame(mech), index=False), ""]
    L += ["## Experiment reports", ""] + [f"- {k}: [{Path(v['report']).name}]({Path(v['report']).name}) · "
                                           f"{v.get('blocks')} complete blocks · best `{v.get('best')}`"
                                           for k, v in reps.items()] + [""]
    L += ["## Recommendation", ""]
    good = [v for v in verdict if v.get("vehicle_hours_reduction_pct") is not None]
    if not good:
        L.append("Inconclusive: no held-out policy had complete matched blocks. See failures above.")
    else:
        top = max(good, key=lambda v: v["vehicle_hours_reduction_pct"])
        win = [v for v in good if v["meets_vehicle_hours_target"] and v["lower_congestion"] and v["background_ok"]
               and v["participant_p95_ok"]]
        if win:
            w = max(win, key=lambda v: v["vehicle_hours_reduction_pct"])
            L.append(f"`{w['policy']}` met the pre-declared development targets on held-out `{w['heldout']}`: "
                     f"{w['vehicle_hours_reduction_pct']:.2f}% less total vehicle time and "
                     f"{w['congested_scope_reduction_pct']:.2f}% less in-scope congested time vs independent routing.")
        elif any(v["consistent_reduction"] and v["lower_congestion"] for v in good):
            top = max((v for v in good if v["consistent_reduction"] and v["lower_congestion"]),
                      key=lambda v: v["vehicle_hours_reduction_pct"])
            L.append(f"Coordination helped but below the 5% target: best held-out `{top['policy']}` "
                     f"({top['heldout']}) cut total vehicle time by {top['vehicle_hours_reduction_pct']:.2f}% and "
                     f"in-scope congested time by {top['congested_scope_reduction_pct']:.2f}%. Keep the simple "
                     "coordinator for the prototype and report the effect size exactly; do not claim citywide "
                     "congestion reduction.")
        else:
            L.append(f"No measurable held-out reduction: `{top['policy']}` ({top['heldout']}) changed total vehicle "
                     f"time by {-top['vehicle_hours_reduction_pct']:+.3f}% ({top['vehicle_hours_mean_diff']:+.2f} "
                     f"veh-h, better in {top['blocks_better']} / worse in {top['blocks_worse']} blocks). Retain "
                     "independent routing as the default; see the mechanism table for why.")
    L += ["", "## Limitations", "",
          "- One held-out event group (Portola) and one development group (Bearrison): families are not independent "
          "event types; uncertainty is broad.",
          "- Participants are a small share of all in-scope vehicles (see adoption table); full compliance is a "
          "controlled setting, not a deployment assumption.",
          "- Teleports are allowed after the configured time and counted (run CSVs); they can relieve simulated "
          "gridlock.",
          "- RL policies are not in this matrix unless listed; see the RL benchmark for them.", ""]
    p = cfg.path("reports") / f"load_balancing_backtest_{backtest_id}.md"
    p.write_text("\n".join(L), encoding="utf-8")
    return p


def _load(root: Path, exps: dict) -> dict:
    """{name: results} for the experiments that have saved results (e.g. copied from another node)."""
    out = {}
    for k, e in exps.items():
        f = root / e.exp / "results.json"
        if f.exists():
            out[k] = json.loads(f.read_text())
    return out


def main(cfg: Config, phase: str = "all", workers: int | None = None, rl: list | None = None, log=print,
         only: list | None = None) -> dict:
    """dev and heldout are independent (they may run on two nodes at once); report combines whatever results
    exist. The selection is computed from dev results only, once, and frozen to selection_<id>.json."""
    root = cfg.path(cfg.benchmark.out_dir)
    root.mkdir(parents=True, exist_ok=True)
    dev_e, held_e = dev_experiments(cfg), heldout_experiments(cfg, rl)
    backtest_id = hashlib.sha256("|".join(e.exp for e in [*dev_e.values(), *held_e.values()]).encode()).hexdigest()[:10]
    (root / f"backtest_{backtest_id}.json").write_text(json.dumps(
        {"dev": {k: e.exp for k, e in dev_e.items()}, "heldout": {k: e.exp for k, e in held_e.items()}}, indent=1))
    todo = {**(dev_e if phase in ("dev", "all") else {}), **(held_e if phase in ("heldout", "all") else {})}
    if only:                                   # e.g. split one backtest across nodes: --only heldout_5
        unknown = set(only) - set(dev_e) - set(held_e)
        if unknown:
            raise SystemExit(f"unknown experiments {sorted(unknown)}; choose from {[*dev_e, *held_e]}")
        todo = {k: e for k, e in todo.items() if k in only}
    if todo:                                   # one process pool for everything this node runs
        log(json.dumps({"running": list(todo)}))
        runner.run_many(list(todo.values()), workers=workers, log=log)
    dev, held = _load(root, dev_e), _load(root, held_e)
    reps = {}
    for k, r in {**dev, **held}.items():
        reps[k] = _write_reports(cfg, k, r)
        log(json.dumps({"report": reps[k]}, default=str))
    sel_path = root / f"selection_{backtest_id}.json"
    sel = None
    if sel_path.exists():
        sel = json.loads(sel_path.read_text())
    elif "screen" in dev:
        sel = select(dev)
        sel_path.write_text(json.dumps(sel, indent=1, default=str))
    if sel:
        log(json.dumps({"selection": {k: sel[k] for k in ("best", "challenger")}}))
    p = final_report(cfg, backtest_id, dev, sel, held, reps)
    log(json.dumps({"final_report": str(p), "dev_experiments": len(dev), "heldout_experiments": len(held)}))
    return {"backtest_id": backtest_id, "report": str(p), "selection": sel}


# ---------------------------------------------------------------- high-adoption sweep
SWEEP_POLICIES = ["forecast_only", "heuristic", "heuristic@lam=120", "batch"]


def sweep_experiments(cfg: Config, levels: list, policies: list) -> dict:
    """Every policy at each participation level on the development (val) and held-out (test) scenarios. A
    descriptive adoption study: no selection step, every policy is reported at every level."""
    dev_s, held_s = runner.choose_scenarios(cfg, "screening"), runner.choose_scenarios(cfg, "heldout")
    E = {}
    for p in levels:
        v, pct = variant(cfg, p), round(100 * p)
        E[f"sweep_dev_{pct}"] = runner.prepare(v, "screening", policies, dev_s, list(cfg.benchmark.seeds))
        E[f"sweep_heldout_{pct}"] = runner.prepare(v, "heldout", policies, held_s, HELDOUT_SEEDS)
    return E


def _metric(pv, pol: str, metric: str, col: str = "mean_rel_pct"):
    r = pv[(pv.policy == pol) & (pv.metric == metric)] if not pv.empty else pv
    return float(r[col].iloc[0]) if len(r) else None


def sweep_report(cfg: Config, sid: str, levels: list, res: dict, reps: dict) -> Path:
    rows = []
    for name, r in res.items():
        S = report.summarize(r)
        pv = S["paired"]
        for pol in [p for p in r["meta"]["policies"] if p != report.BASE]:
            t = S["targets"].get(pol) or {}
            rows.append({"participation": r["meta"]["participation"],
                         "split": "held-out" if name.startswith("sweep_heldout") else "dev", "policy": pol,
                         "blocks": len(S["blocks"]), "vehicle_hours %": _metric(pv, pol, "vehicle_hours"),
                         "veh-h diff": _metric(pv, pol, "vehicle_hours", "mean_diff"),
                         "better/worse": f"{t.get('blocks_better')}/{t.get('blocks_worse')}",
                         "congested in-scope %": _metric(pv, pol, "congested_h_scope"),
                         "congested all %": _metric(pv, pol, "congested_h_all"),
                         "background mean %": _metric(pv, pol, "other_trip_s_mean"),
                         "participant p95 %": _metric(pv, pol, "part_trip_s_p95"),
                         "consistent reduction": bool(t.get("consistent_reduction"))})
    df = pd.DataFrame(rows).sort_values(["split", "participation", "policy"]) if rows else pd.DataFrame()
    held = df[(df.split == "held-out") & df["consistent reduction"]] if not df.empty else df
    L = [f"# High-adoption sweep `{sid}`", "",
         "> **Synthetic.** Closed-loop SUMO replays; participation, compliance (100%) and behaviour are assumptions.", "",
         f"Participation levels {levels} of eligible drivers (car trips departing in the 30-min decision window); "
         "`participants / in-scope` in the mechanism table gives the share of all vehicles. Percentages are mean paired "
         "changes vs `forecast_only` on common complete blocks (negative = better). 'consistent reduction' = absolute "
         "and relative means agree and the policy wins at least 2/3 of blocks.", "",
         "## Outcomes by participation level", "",
         report._md(df.round(4), index=False) if not df.empty else "(no results)", "", "## Summary", ""]
    if len(held):
        b = held.sort_values("vehicle_hours %").iloc[0]
        L.append(f"Best consistent held-out reduction: `{b['policy']}` at {b['participation']:.0%} participation, "
                 f"{-b['vehicle_hours %']:.2f}% less total vehicle time and {-(b['congested in-scope %'] or 0):.2f}% "
                 "less in-scope congested time vs independent routing.")
    else:
        L.append("No policy gave a consistent held-out reduction in total vehicle time at these participation levels.")
    mech = _mechanism(res)
    L += ["", "## Mechanism", "", report._md(pd.DataFrame(mech), index=False) if mech else "", "",
          "## Experiment reports", ""]
    L += [f"- {k}: [{Path(v['report']).name}]({Path(v['report']).name}) · {v.get('blocks')} complete blocks"
          for k, v in reps.items()] + [""]
    p = cfg.path("reports") / f"adoption_sweep_{sid}.md"
    p.write_text("\n".join(L), encoding="utf-8")
    return p


def sweep(cfg: Config, levels: list, policies: list | None = None, run: bool = True, workers: int | None = None,
          only: list | None = None, log=print) -> dict:
    policies = policies or SWEEP_POLICIES
    root = cfg.path(cfg.benchmark.out_dir)
    root.mkdir(parents=True, exist_ok=True)
    E = sweep_experiments(cfg, levels, policies)
    sid = hashlib.sha256("|".join(e.exp for e in E.values()).encode()).hexdigest()[:10]
    (root / f"sweep_{sid}.json").write_text(json.dumps({k: e.exp for k, e in E.items()}, indent=1))
    if only:
        unknown = set(only) - set(E)
        if unknown:
            raise SystemExit(f"unknown experiments {sorted(unknown)}; choose from {list(E)}")
    todo = {k: e for k, e in E.items() if not only or k in only}
    if run and todo:
        log(json.dumps({"running": list(todo)}))
        runner.run_many(list(todo.values()), workers=workers, log=log)
    res = _load(root, E)
    reps = {k: _write_reports(cfg, k, r) for k, r in res.items()}
    p = sweep_report(cfg, sid, levels, res, reps)
    log(json.dumps({"sweep_report": str(p), "experiments": len(res), "of": len(E)}))
    return {"sweep_id": sid, "report": str(p)}
