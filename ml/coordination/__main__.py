"""python -m coordination {fixture|audit|route|demo|serve|replay-context|env-check|prewarm|train-rl|benchmark|backtest} --config configs/coordinated_routing_v2.yaml"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import config as cfg_mod
from . import fixture as fx
from .forecast_store import ForecastInvalid, load_files
from .network import sha256_file
from .runtime import build, load_network
from .schemas import RouteRequest, iso
from .selectors import NAMES

# default audit trip: Castro -> SoMa (near the Folsom Street Fair footprint of the default fixture run)
DEFAULT_FROM = (-122.4350, 37.7625)
DEFAULT_TO = (-122.4094, 37.7726)


def _pt(s: str | None, default):
    return default if not s else tuple(float(x) for x in s.split(","))


def cmd_fixture(cfg, a):
    net = load_network(cfg)
    sc_path = cfg.path(cfg.network.sim_root) / "batches" / a.batch / "scenarios.json"
    closures, info = fx.closures_from_run(sc_path, a.run)
    issued = a.issued_at
    if issued == "auto":
        start = pd.Timestamp(info["public_hours_utc"][0]) if info["public_hours_utc"] else closures.closure_begin.min()
        issued = (start - pd.Timedelta(minutes=30)).floor("10min").isoformat()
    df, closures, meta = fx.build(net, issued, closures, seed=a.seed, bucket_min=cfg.forecast.bucket_min,
                                  horizons=cfg.forecast.horizons)
    meta["closures_from"] = info
    out = fx.write(df, closures, meta, cfg.path(a.output or cfg.forecast.path))
    print(json.dumps({"written": str(out), "issued_at": meta["issued_at"], "rows": len(df),
                      "closure_rows": len(closures), "availability": meta["availability_counts"],
                      "label": meta["FIXTURE"]}, indent=1))


def cmd_audit(cfg, a):
    t0 = time.perf_counter()
    net = load_network(cfg, use_cache=not a.no_cache)
    t_net = time.perf_counter() - t0
    fpath = cfg.path(cfg.forecast.path)
    rep = {"config": cfg.name, "config_hash": cfg.hash(), "network": {"version": net.version, **net.stats},
           "network_load_s": round(t_net, 2)}
    try:
        snap = load_files(fpath, net, cfg.forecast.bucket_min, cfg.forecast.horizons)
        rep["forecast"] = {"file": str(fpath), "sha256": sha256_file(fpath), **snap.summary(),
                           "coverage": snap.coverage, "valid": True}
        if snap.fixture:
            rep["forecast"]["WARNING"] = ("labeled development FIXTURE, not a trained forecast; trained-forecast "
                                          "integration remains outstanding until `python -m forecast predict` output exists")
    except ForecastInvalid as e:
        rep["forecast"] = {"file": str(fpath), "valid": False, "problems": e.problems}
        print(json.dumps(rep, indent=1, default=str))
        sys.exit(1)
    # endpoint coverage: routable roads = has a usable forecast in some interval and both in- and out-arcs
    routable = snap.ok.any(1) & (net.indeg > 0) & (net.outdeg > 0)
    rep["routing_coverage"] = {"roads": net.n, "routable_roads": int(routable.sum()),
                               "routable_share": round(float(routable.mean()), 4),
                               "unroutable_by_static_availability": pd.Series(net.static_availability[~routable]).value_counts().to_dict()}
    coord = build(cfg, db_path=":memory:", now=a.now, net=net)
    t1 = time.perf_counter()
    r = coord.recommend(RouteRequest("audit-1", _pt(a.origin, DEFAULT_FROM), _pt(a.destination, DEFAULT_TO),
                                     coord.clock(), reserve=False))
    rep["end_to_end_route"] = {k: r.get(k) for k in ("outcome", "reason", "is_fastest", "reasons", "degradation")}
    if r.get("outcome") == "preview":
        rec = r["recommended"]
        rep["end_to_end_route"].update({"eta_s": rec["forecast_eta_sec"], "distance_m": rec["distance_m"],
                                        "roads": len(rec["road_segment_ids"]),
                                        "alternatives": [(x["candidate_id"], x["forecast_eta_sec"], x["extra_travel_sec"])
                                                         for x in r["alternatives"]],
                                        "latency_ms": r["latency_ms"]})
    rep["end_to_end_route"]["wall_ms"] = round((time.perf_counter() - t1) * 1000, 1)
    out = cfg.path(cfg.run_root) / f"audit_{time.strftime('%Y%m%dT%H%M%S')}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "audit.json").write_text(json.dumps(rep, indent=1, default=str))
    rep["written"] = str(out / "audit.json")
    print(json.dumps(rep, indent=1, default=str))


def cmd_route(cfg, a):
    coord = build(cfg, db_path=":memory:", now=a.now, selector=a.selector)
    r = coord.recommend(RouteRequest("cli-1", _pt(a.origin, DEFAULT_FROM), _pt(a.destination, DEFAULT_TO),
                                     coord.clock(), reserve=False))
    if not a.full and r.get("outcome") == "preview":
        for v in [r["recommended"]] + r["alternatives"]:
            v.pop("geometry", None)
            v["road_segment_ids"] = f"{len(v['road_segment_ids'])} roads"
    print(json.dumps(r, indent=1, default=str))


def cmd_demo(cfg, a):
    """Several users sent to one destination, decided with each selector from the same empty initial ledger.
    Illustrates allocation behaviour only: these are selection diagnostics, not measured congestion."""
    net = load_network(cfg)
    rng = np.random.default_rng(a.seed)
    o0 = np.array(_pt(a.origin, DEFAULT_FROM))
    dest = _pt(a.destination, DEFAULT_TO)
    origins = [tuple(o0 + rng.normal(0, 0.004, 2)) for _ in range(a.users)]
    rows = []
    for sel in a.selectors.split(","):
        coord = build(cfg, db_path=":memory:", now=a.now, selector=sel, net=net)
        t = coord.clock()
        reqs = [RouteRequest(f"demo-{i}", origins[i], dest, t) for i in range(a.users)]
        t0 = time.perf_counter()
        res = []
        for i in range(0, len(reqs), a.batch):
            res += coord.recommend_batch(reqs[i:i + a.batch])
        wall = time.perf_counter() - t0
        ok = [r for r in res if r.get("outcome") == "recommendation"]
        for r in ok:
            coord.accept(r["assignment"]["assignment_id"], r["assignment"]["version"])
        ratio = [v / coord.score.budget[c[0]] for c, v in coord.ledger.load.items()]
        phi = sum(coord.score.coef(c) * v ** 2 for c, v in coord.ledger.load.items())
        extra = [r["recommended"]["extra_travel_sec"] for r in ok]
        rows.append({"selector": sel, "recommended": len(ok), "unsupported": len(res) - len(ok),
                     "fallbacks": sum(1 for r in ok if r["selector"]["fallback_reason"]),
                     "not_fastest": sum(1 for r in ok if not r["is_fastest"]),
                     "distinct_routes": len({r["recommended"]["candidate_id"] for r in ok}),
                     "mean_extra_travel_s": round(float(np.mean(extra)), 1) if extra else None,
                     "max_extra_travel_s": round(float(np.max(extra)), 1) if extra else None,
                     "max_load_over_budget": round(float(max(ratio)), 3) if ratio else None,
                     "phi": round(phi, 4), "wall_s": round(wall, 2)})
    print("allocation diagnostics (selection-score units, NOT predicted or measured congestion):")
    print(pd.DataFrame(rows).to_string(index=False))


def _rl_setup(cfg, a):
    from .rl import scenario
    net = load_network(cfg)
    runs = a.runs.split(",") if getattr(a, "runs", None) else None
    train = scenario.load(cfg, "train", runs)
    val = scenario.load(cfg, "val")
    if not train:
        raise SystemExit("no train scenarios")
    return net, train, val, scenario.manifest(cfg, train + val)


def cmd_env_check(cfg, a):
    """Gate 1: the same scenario/seed with two deliberately different routing policies must produce different
    actual routes and measured outcomes, with identical demand. No neural network involved."""
    from .rl import scenario
    from .rl.evaluate import act_alternative, act_fastest, run_episodes
    from .rl.sumo_env import RouteChoiceEnv
    net = load_network(cfg)
    spec = scenario.load(cfg, None, [a.run])
    if not spec:
        raise SystemExit(f"run {a.run} not found")
    rows = {}
    for name, act in (("fastest", act_fastest), ("alternative", act_alternative)):
        env = RouteChoiceEnv(cfg, net, spec, policy_name=f"gate_{name}", allow_debug_forecast=a.debug_forecast,
                             tag=f"env_check_{name}")
        r = run_episodes(env, act, 1, [{"scenario": a.run, "seed_offset": a.seed_offset}])[0]
        routes = {}
        for t in env.parts:
            x = env.coord.storage.by_request(f"{a.run}|{t.id}")
            if x is not None:
                routes[x.request_id] = tuple(x.route)
        rows[name] = {"return": r["return"], "decisions": r["decisions"], "summary": r["summary"], "routes": routes}
        env.close()
    f, g = rows["fastest"], rows["alternative"]
    common = set(f["routes"]) & set(g["routes"])
    diff = sum(f["routes"][k] != g["routes"][k] for k in common)
    fs, gs = f["summary"], g["summary"]
    rep = {"run": a.run, "seed_offset": a.seed_offset, "forecast_mode": cfg.env.forecast_mode,
           "participants": fs["participants"], "decisions": [f["decisions"], g["decisions"]],
           "participants_with_different_routes": diff, "of_common": len(common),
           "in_scope_vehicle_hours": [fs["in_scope_vehicle_hours"], gs["in_scope_vehicle_hours"]],
           "participant_mean_duration_s": [fs["participant_mean_duration_s"], gs["participant_mean_duration_s"]],
           "in_scope_vehicles_equal": fs["in_scope_vehicles"] == gs["in_scope_vehicles"],
           "invalid_routes": [fs["invalid_route"], gs["invalid_route"]],
           "readback_mismatch": [fs["route_readback_mismatch"], gs["route_readback_mismatch"]],
           "unfinished": [fs.get("unfinished"), gs.get("unfinished")],
           "used_warm_state": [fs["used_warm_state"], gs["used_warm_state"]],
           "wall_s": [fs["wall"], gs["wall"]]}
    rep["gate_passed"] = bool(diff > 0 and rep["in_scope_vehicles_equal"] and sum(rep["invalid_routes"]) == 0
                              and rep["in_scope_vehicle_hours"][0] != rep["in_scope_vehicle_hours"][1])
    out = cfg.path(cfg.run_root) / f"env_check_{time.strftime('%Y%m%dT%H%M%S')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({**rep, "summaries": {"fastest": fs, "alternative": gs}}, indent=1, default=str))
    print(json.dumps(rep, indent=1, default=str))
    print("written", out)


def cmd_train_rl(cfg, a):
    from .rl.sumo_env import RouteChoiceEnv
    from .rl.train import run_dir, train_ddqn, train_ppo
    for k in ("max_decisions", "wall_hours", "n_steps"):
        if getattr(a, k) is not None:
            setattr(cfg.rl, k, getattr(a, k))
    if a.participation is not None:
        cfg.env.participation = a.participation
    if a.max_participants is not None:
        cfg.env.max_participants = a.max_participants
    net, train, val, manifest = _rl_setup(cfg, a)
    rd = run_dir(cfg, a.algo, a.seed, a.name)
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "scenario_manifest.json").write_text(json.dumps(manifest, indent=1, default=str))

    def envf(sd):
        return RouteChoiceEnv(cfg, net, train, policy_name=f"rl_{a.algo}", allow_debug_forecast=a.debug_forecast,
                              seed=sd, tag=f"train_{a.algo}")

    def evalf(sd):
        return RouteChoiceEnv(cfg, net, val, policy_name=f"rl_{a.algo}_val", allow_debug_forecast=a.debug_forecast,
                              seed=sd, tag=f"val_{a.algo}")

    if a.async_actors is not None:
        from .rl.async_train import route_env_factories, train_async
        trf, vaf = route_env_factories(cfg, a.debug_forecast)
        algo = "appo" if a.algo == "ppo" else "ddqn"
        s = train_async(cfg, algo, a.seed, trf, None if a.no_eval else vaf, net.version, manifest, name=a.name,
                        n_actors=a.async_actors or cfg.rl.n_envs, rollout=a.rollout)
        print(json.dumps(s, indent=1, default=str))
        return
    fn = train_ppo if a.algo == "ppo" else train_ddqn
    s = fn(cfg, a.seed, envf, evalf if (val and not a.no_eval) else None, net.version, manifest,
           resume=a.resume, name=a.name)
    print(json.dumps(s, indent=1, default=str))


def cmd_benchmark(cfg, a):
    from .benchmark import report, runner
    if a.workers:
        cfg.benchmark.workers = a.workers
    for p in (a.policies or "").split(","):
        if p.startswith("rl_") and "=" in p:          # --policies rl_ppo=path overrides a checkpoint
            name, ck = p.split("=", 1)
            cfg.benchmark.checkpoints[name] = ck
    policies = [p.split("=", 1)[0] if p.startswith("rl_") else p for p in a.policies.split(",")] if a.policies else None
    seeds = [int(x) for x in a.seeds.split(",")] if a.seeds else None
    res = runner.run(cfg, a.suite, policies, a.scenarios.split(",") if a.scenarios else None, seeds,
                     resume=not a.no_resume)
    exp = res["meta"]["experiment_id"]
    out = cfg.path(cfg.benchmark.out_dir) / exp
    name = f"coordination_benchmark_{exp}"
    if a.suite == "static":
        rep = report.write_static(res, cfg.path("reports") / f"{name}.md")
    else:
        rep = report.write(res, cfg.path("reports") / f"{name}.md", out / "runs.csv")
    print(json.dumps(rep, indent=1, default=str))


def cmd_backtest(cfg, a):
    from .benchmark import backtest
    if a.workers:
        cfg.benchmark.workers = a.workers
    rl = []
    for p in (a.rl or "").split(","):
        if p:
            name, _, ck = p.partition("=")
            if ck:
                cfg.benchmark.checkpoints[name] = ck
            rl.append(name)
    only = [x for x in (a.only or "").split(",") if x] or None
    if a.phase in ("fireworks", "fireworks-report"):
        print(json.dumps(backtest.fireworks(cfg, run=a.phase == "fireworks", workers=a.workers, only=only),
                         indent=1, default=str))
        return
    if a.phase in ("sweep", "sweep-report"):
        levels = [float(x) for x in (a.levels or "0.8,0.9,1.0").split(",")]
        pols = [x for x in (a.sweep_policies or "").split(",") if x] or None
        print(json.dumps(backtest.sweep(cfg, levels, pols, run=a.phase == "sweep", workers=a.workers, only=only),
                         indent=1, default=str))
        return
    print(json.dumps(backtest.main(cfg, a.phase, a.workers, rl, only=only), indent=1, default=str))


def cmd_prewarm(cfg, a):
    """Verified warm SUMO states (end of the history period) for every scenario x simulation seed of the given
    splits, built in parallel once, so training/benchmark environments load them instead of racing to build them."""
    from concurrent.futures import as_completed
    from .benchmark.runner import _pool, warm_task
    from .rl import scenario
    load_network(cfg)
    if a.workers:
        cfg.benchmark.workers = a.workers
    ids = [s.scenario_id for sp in a.splits.split(",") for s in scenario.load(cfg, sp)]
    pairs = [(i, k) for i in ids for k in cfg.env.sim_seed_offsets]
    t0, done, failed = time.time(), 0, []
    d = cfg.to_dict()
    with _pool(len(pairs), cfg) as ex:
        futs = {ex.submit(warm_task, d, i, k, a.debug_forecast): (i, k) for i, k in pairs}
        for f in as_completed(futs):
            try:
                f.result()
                done += 1
            except Exception as e:
                failed.append({"scenario": futs[f][0], "seed_offset": futs[f][1], "error": str(e)[:300]})
    print(json.dumps({"splits": a.splits, "states": len(pairs), "built_or_verified": done, "failed": failed,
                      "wall_s": round(time.time() - t0, 1)}, indent=1))
    if failed:
        sys.exit(1)


def cmd_serve(cfg, a):
    from .service import serve
    host, port = a.host or cfg.service.host, a.port or cfg.service.port
    if a.input == "replay":
        from . import replay
        runtime = replay.from_config(cfg, load_network(cfg), a.selector).start()
        serve(None, host, port, runtime=runtime)
    elif a.input == "live":
        from . import live
        serve(None, host, port, runtime=live.from_config(cfg, load_network(cfg), a.selector))
    else:
        serve(build(cfg, now=a.now, selector=a.selector), host, port)


def cmd_replay_context(cfg, a):
    """Package one recorded run for `serve --input replay`: its history columns + context.json (scheduled cases)."""
    from . import replay
    batch_dir = cfg.path(cfg.network.sim_root) / "batches" / a.batch
    src = batch_dir / "export" / f"sim_{a.run}.parquet"
    out = cfg.path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tab = pd.read_parquet(src, columns=replay.HISTORY_COLUMNS)
    tab.to_parquet(out / f"{a.run}.parquet", index=False)
    ctx = replay.build_context(batch_dir, a.run, load_network(cfg).version)
    (out / f"{a.run}.context.json").write_text(json.dumps(ctx, indent=1, default=str))
    s = replay.ReplaySource(out / f"{a.run}.parquet", out / f"{a.run}.context.json", cfg.forecast.bucket_min)
    print(json.dumps({"run": a.run, "written": str(out), "network_version": ctx["network_version"],
                      "cases": len(ctx.get("cases", [])), "first_issue": iso(s.first_issue),
                      "last_issue": iso(s.last_issue)}, indent=1))


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m coordination")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, **kw):
        s = sub.add_parser(name, **kw)
        s.add_argument("--config", default="configs/coordinated_routing_v2.yaml")
        return s

    s = add("fixture", help="write a labeled contract-shaped FIXTURE forecast (not a model output)")
    s.add_argument("--batch", default="b3_verify")
    s.add_argument("--run", default="b3_verify_folsom_arrival_f000_s0_event")
    s.add_argument("--issued-at", default="auto", help="ISO UTC or 'auto' = 30 min before the event's public start")
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--output")
    for name in ("audit", "route", "demo", "serve"):
        s = add(name)
        s.add_argument("--now", default="issued", help="'issued' (issue time + 60 s, replay clock), 'wall' or ISO UTC")
        if name in ("audit", "route", "demo"):
            s.add_argument("--origin", help="lon,lat")
            s.add_argument("--destination", help="lon,lat")
        if name in ("route", "serve"):
            s.add_argument("--selector", choices=NAMES)
        if name == "route":
            s.add_argument("--full", action="store_true", help="include geometry and road ids")
        if name == "audit":
            s.add_argument("--no-cache", action="store_true")
        if name == "demo":
            s.add_argument("--users", type=int, default=40)
            s.add_argument("--batch", type=int, default=8)
            s.add_argument("--seed", type=int, default=0)
            s.add_argument("--selectors", default="forecast_only,heuristic,batch")
        if name == "serve":
            s.add_argument("--host")
            s.add_argument("--port", type=int)
            s.add_argument("--input", choices=["file", "replay", "live"], default="file",
                           help="file = forecast.path (+ POST /v1/forecast/refresh); replay = forecast service fed "
                                "with the recorded run in the replay section, under a replay clock; live = congestion "
                                "map from Tiger/Mongo written by the forecaster, refreshed on demand")
    s = add("replay-context", help="package a recorded run (history + context.json) for serve --input replay")
    s.add_argument("--batch", default="b3_main")
    s.add_argument("--run", default="b3_main_portola_full_f025_s0_event")
    s.add_argument("--out", default="data/coordination/replay")
    s = add("benchmark", help="matched selector comparison in SUMO (static|profile|screening|heldout)")
    s.add_argument("--suite", default="static", choices=["static", "profile", "screening", "heldout"])
    s.add_argument("--policies", help="comma list (default benchmark.policies); rl_ppo=<ckpt dir> overrides a checkpoint")
    s.add_argument("--scenarios", help="comma-separated run ids (default: chosen from the suite's split)")
    s.add_argument("--seeds", help="comma-separated simulation seed offsets")
    s.add_argument("--workers", type=int)
    s.add_argument("--no-resume", action="store_true", help="rerun tasks even if this experiment id has results")
    s = add("backtest", help="load-balancing backtest: dev screening/adoption/compliance -> frozen selection -> "
                             "held-out -> report (LOAD_BALANCING_BACKTEST_PLAN.md)")
    s.add_argument("--phase", default="all", choices=["dev", "heldout", "report", "all", "sweep", "sweep-report",
                                                    "fireworks", "fireworks-report"])
    s.add_argument("--levels", help="sweep: participation levels (share of eligible drivers), default 0.8,0.9,1.0")
    s.add_argument("--sweep-policies", help="sweep: policies (default forecast_only,heuristic,heuristic@lam=120,batch)")
    s.add_argument("--workers", type=int)
    s.add_argument("--rl", help="optional held-out RL policies: rl_ppo=<ckpt dir>,rl_ddqn=<ckpt dir>")
    s.add_argument("--only", help="run only these experiments (profile,screen,adopt_15,adopt_30,comply_75,comply_50,"
                                  "heldout_5,heldout_30), e.g. to split one backtest across nodes")
    s = add("prewarm", help="build verified warm SUMO states for all scenarios of the given splits (parallel)")
    s.add_argument("--splits", default="train,val,test")
    s.add_argument("--workers", type=int)
    s.add_argument("--debug-forecast", action="store_true",
                   help="refresh with the labeled persistence stand-in (the saved state does not depend on it)")
    s = add("env-check", help="gate: two different routing policies on one scenario must change routes/outcomes")
    s.add_argument("--run", default="b3_verify_folsom_arrival_f000_s0_event")
    s.add_argument("--seed-offset", type=int, default=0)
    s.add_argument("--debug-forecast", action="store_true", help="allow labeled fixture/persistence debug forecasts")
    s = add("train-rl", help="MaskablePPO or masked Double DQN on the SUMO route-choice environment (bounded)")
    s.add_argument("--algo", choices=["ppo", "ddqn"], default="ppo")
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--resume", action="store_true")
    s.add_argument("--name")
    s.add_argument("--runs", help="comma-separated train run ids (default: every train-split run)")
    s.add_argument("--max-decisions", type=int)
    s.add_argument("--wall-hours", type=float)
    s.add_argument("--n-steps", type=int)
    s.add_argument("--no-eval", action="store_true")
    s.add_argument("--debug-forecast", action="store_true")
    s.add_argument("--async-actors", type=int, nargs="?", const=0, default=None,
                   help="asynchronous actor-learner training with N actor processes (default rl.n_envs); "
                        "ppo -> masked actor-critic PPO ('appo'), ddqn -> masked Double DQN")
    s.add_argument("--rollout", type=int, default=8192, help="async PPO: decisions per update")
    s.add_argument("--participation", type=float, help="override env.participation")
    s.add_argument("--max-participants", type=int, help="override env.max_participants")
    a = p.parse_args(argv)
    cfg = cfg_mod.load(a.config)
    {"fixture": cmd_fixture, "audit": cmd_audit, "route": cmd_route, "demo": cmd_demo, "serve": cmd_serve,
     "replay-context": cmd_replay_context,
     "env-check": cmd_env_check, "train-rl": cmd_train_rl, "benchmark": cmd_benchmark,
     "prewarm": cmd_prewarm, "backtest": cmd_backtest}[a.cmd](cfg, a)


if __name__ == "__main__":
    main()
