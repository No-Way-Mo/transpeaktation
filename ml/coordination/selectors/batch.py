"""Policy C: bounded joint selection for one batch of arrived requests with OR-Tools CP-SAT.

    minimise  sum[i,k] ETA[i,k] x[i,k] + lambda * Phi(L_fixed + sum[i,k] contribution[i,k] x[i,k])

* x[i,k] Boolean, exactly one per request that has valid candidates (requests without any are failures handled by
  the coordinator, never silently dropped). Existing reservations are fixed; contributions are fixed for the solve.
* Integer model only. Objective unit = 1 / time_scale seconds; load unit = 1 / load_scale participating entries.
  Contributions are rounded to load units (exact with the default kernel [1.0]).
* Per cell, cost G(l) = time_scale * lambda * coef * ((L0 + l/load_scale)^2 - L0^2) is convex in the added load l.
  - cells touched by one request only: G is folded exactly into that request's x coefficients;
  - shared cells: y_c >= secant_j(l) for consecutive breakpoints j (step = gcd of the contributions). The max of
    these secants is the piecewise-linear interpolation of G, exact at every reachable load; secant coefficients
    are rounded to integers (error <= ~1 objective unit near the binding piece). Only touched cells are built.
* The heuristic assignment is the solver hint. The returned plan is re-scored with the shared exact function and
  the heuristic plan is kept if it scores better (the approximation cannot make things worse than the fallback).
An optimum here is optimal for this candidate set and penalty formulation, not for real traffic.
"""
from __future__ import annotations

import math
import time
from functools import reduce

from ..config import BatchCfg
from ..schemas import SelectionContext, SelectionResult
from .base import Selector, exact_joint_score, sequential, valid_indices

MAX_COEF = 2 ** 40


class Batch(Selector):
    name = "batch"
    version = "batch_cpsat-v1"

    def __init__(self, cfg: BatchCfg):
        self.cfg = cfg

    def select(self, ctx: SelectionContext) -> SelectionResult:
        from ortools.sat.python import cp_model

        t0 = time.perf_counter()
        TS, LS = self.cfg.time_scale, self.cfg.load_scale
        heur = sequential(ctx, ctx.lam, "heuristic", "heuristic-v1")
        items = [it for it in ctx.items if valid_indices(it)]
        if not items:
            heur.policy, heur.policy_version = self.name, self.version
            return heur

        m = cp_model.CpModel()
        x: dict[tuple, object] = {}
        lin: dict[tuple, float] = {}
        for i, it in enumerate(items):
            ks = valid_indices(it)
            for k in ks:
                x[i, k] = m.NewBoolVar(f"x_{i}_{k}")
                lin[i, k] = TS * it.candidates[k].eta_s
            m.AddExactlyOne(x[i, k] for k in ks)

        # which (request, candidate) touch each cell, with integer load contribution
        touch: dict = {}
        for (i, k) in x:
            for c, w in items[i].candidates[k].cells.items():
                q = int(round(w * LS))
                if q > 0:
                    touch.setdefault(c, {}).setdefault(i, {})[k] = q

        def G(c, l_units: float) -> float:
            L0 = ctx.base_load(c)
            return TS * ctx.lam * ctx.cell_coef(c) * ((L0 + l_units / LS) ** 2 - L0 ** 2)

        n_shared, n_secants = 0, 0
        obj_terms = []
        for c, by_req in touch.items():
            if ctx.lam == 0:
                break
            if len(by_req) == 1:
                (i, ks), = by_req.items()
                for k, q in ks.items():
                    lin[i, k] += G(c, q)
                continue
            n_shared += 1
            qs = [q for ks in by_req.values() for q in ks.values()]
            step = reduce(math.gcd, qs)
            lmax = sum(max(ks.values()) for ks in by_req.values())
            load = m.NewIntVar(0, lmax, f"l_{n_shared}")
            m.Add(load == sum(q * x[i, k] for i, ks in by_req.items() for k, q in ks.items()))
            ub = int(math.ceil(G(c, lmax))) + 2
            if ub > MAX_COEF:
                raise OverflowError(f"cell cost bound {ub} exceeds {MAX_COEF}; lower time_scale")
            y = m.NewIntVar(0, ub, f"y_{n_shared}")
            for j in range(0, lmax, step):
                g0, g1 = G(c, j), G(c, j + step)
                slope = (g1 - g0) / step
                s_int = int(round(slope))
                m.Add(y >= int(round(g0)) + s_int * (load - j))
                n_secants += 1
            obj_terms.append(y)
        coefs = {key: int(round(v)) for key, v in lin.items()}
        if max(abs(v) for v in coefs.values()) > MAX_COEF:
            raise OverflowError("objective coefficient overflow; lower time_scale")
        m.Minimize(sum(coefs[key] * var for key, var in x.items()) + sum(obj_terms))

        for i, it in enumerate(items):
            hk = heur.choices.get(it.request.request_id)
            for k in valid_indices(it):
                m.AddHint(x[i, k], 1 if k == hk else 0)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = max(self.cfg.solve_ms, 1.0) / 1000.0
        solver.parameters.num_workers = self.cfg.workers
        solver.parameters.random_seed = ctx.seed
        st = solver.Solve(m)
        status = {cp_model.OPTIMAL: "optimal", cp_model.FEASIBLE: "feasible",
                  cp_model.UNKNOWN: "timeout_no_solution", cp_model.INFEASIBLE: "infeasible",
                  cp_model.MODEL_INVALID: "invalid"}.get(st, "unknown")
        info = {"status": status, "requests": len(items), "vars": len(x), "cells": len(touch),
                "shared_cells": n_shared, "secants": n_secants, "wall_ms": solver.WallTime() * 1000}
        if status in ("optimal", "feasible"):
            info.update({"objective": solver.ObjectiveValue() / TS, "bound": solver.BestObjectiveBound() / TS})
            info["gap"] = (info["objective"] - info["bound"]) / max(abs(info["objective"]), 1e-9)
            choices = {it.request.request_id: next(k for k in valid_indices(it) if solver.Value(x[i, k]))
                       for i, it in enumerate(items)}
            s_solver = exact_joint_score(ctx, choices)
            s_heur = exact_joint_score(ctx, heur.choices)
            info["exact_score_solver"], info["exact_score_heuristic"] = s_solver["score"], s_heur["score"]
            if s_solver["score"] <= s_heur["score"] + 1e-9:
                info["kept"] = "solver"
                res = SelectionResult(choices=choices, policy=self.name, policy_version=self.version,
                                      diagnostics=heur.diagnostics, status=status)
                for it in items:
                    rid = it.request.request_id
                    k = choices[rid]
                    fastest = min(valid_indices(it), key=lambda j: (it.candidates[j].eta_s, it.candidates[j].candidate_id))
                    res.reasons[rid] = ["fastest_candidate" if k == fastest else "joint_batch_allocation"]
            else:
                info["kept"] = "heuristic_better_under_exact_score"
                res = heur
                res.policy, res.policy_version, res.status = self.name, self.version, "heuristic_kept"
        else:
            info["kept"] = "heuristic_fallback"
            res = heur
            res.policy, res.policy_version, res.status = self.name, self.version, f"fallback:{status}"
        for it in ctx.items:
            if not valid_indices(it):
                res.reasons[it.request.request_id] = ["no_valid_candidate"]
        res.solver = info
        res.runtime_ms = (time.perf_counter() - t0) * 1000
        return res
