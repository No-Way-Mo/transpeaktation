"""Act 1 = the original demo run (demo/baseline.data.js on origin/main, untouched); Act 2 = our PPO-wide run.

    python -m coordination.demo_combine <original baseline.data.js> <ours baseline.data.js> <out>

Used for demo/baseline.data.js (ml/SIMULATION_EXPERIMENT_STANDARD.md, section 10): <original> = the file on main
before act 2 existed (git show <commit>:demo/baseline.data.js), <ours> = coordination.demo_replay output.

Ours was exported by ml/coordination/demo_replay.py on transPEAKtation's net_v3 (baseline = forecast_only, ml = PPO v2
+ wider search). Only its `ml` variant is taken. Its road indices are shifted past the original's road_shapes (our
shapes appended), its 5-min road frames are repeated for each minute (the page uses one `period`), and our same-setup
baseline all-car totals are kept as `ml_reference` so captions compare Act 2 with the fastest-route run of the SAME
setup, not with Act 1's different simulation.
"""
import json
import sys


def load(p):
    s = open(p, encoding="utf-8").read()
    return json.loads(s[s.index("{"):s.rindex("}") + 1])


orig, ours, out = load(sys.argv[1]), load(sys.argv[2]), sys.argv[3]
assert orig["end"] == ours["end"] and orig["users"] == ours["users"], "horizon / riders differ"
key = lambda v: [(r[0], r[1], r[4], r[5]) for r in v["vehicles"]]
assert key(orig["variants"]["baseline"]) == key(ours["variants"]["ml"]), "riders, requested times, starts or ends differ"
off = len(orig["road_shapes"])
rep = ours["period"] // orig["period"]
assert rep * orig["period"] == ours["period"]
ml = dict(ours["variants"]["ml"])
frames = []
for f in ml["roads"]:
    g = [x + off if i % 3 == 0 else x for i, x in enumerate(f)]
    frames += [g] * rep
n = -(-orig["end"] // orig["period"])
ml["roads"] = (frames + [frames[-1]] * n)[:n]
data = dict(orig)
data["road_shapes"] = orig["road_shapes"] + ours["road_shapes"]
data["variants"] = {"baseline": orig["variants"]["baseline"], "ml": ml}
data["placeholder"] = False
data["ml_models"] = ["ml:ppo_v2_wide"]
ob = ours["variants"]["baseline"]
data["ml_reference"] = {
    "what": "fastest route for everyone, same setup as act 2 (transPEAKtation net_v3, SUMO teleports cars stuck > 300 s)",
    "totals": ob["totals"], "all": ob["all"]}
data["ml_setup"] = {"network": "transPEAKtation net_v3 (not the OSM import of act 1)", "teleport_after_s": 300,
                    "road_speed_period_s": ours["period"], "routing": "every car on the app, PPO v2 + wider candidate search",
                    "run": ours["run"], "crowd": ours.get("crowd"), "replay_notes": ours.get("replay_notes")}
with open(out, "w", encoding="utf-8") as fh:
    fh.write("// Act 1: demo/sumo/view.py run (unchanged). Act 2 + ml_reference: ml/coordination/demo_replay.py; combined.\n"
             "window.BASELINE = " + json.dumps(data, separators=(",", ":")) + ";\n")
print(json.dumps({"out": out, "roads_orig": off, "roads_total": len(data["road_shapes"]), "frames": len(ml["roads"]),
                  "act1_arrived": orig["variants"]["baseline"]["all"]["counts"], "act2_arrived": ml["all"]["counts"],
                  "ref_arrived": ob["all"]["counts"]}, indent=1))
