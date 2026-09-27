# Guide: the second half of the pitch from a real SUMO run

The video (`demo/index.html`) has two acts:

- **Act 1 (0–27 s)** replays the SUMO baseline: the July 4 fireworks exodus, 1,000 app riders + 6,000 other
  cars, everyone on their own fastest route. The numbers are SUMO's.
- **Act 2 (27–51.5 s)** is the transPEAKtation half. Until a second SUMO run exists it plays the **concept
  animation** (an illustrative toy model, labelled as such). Once `demo/baseline.data.js` contains an `ml`
  variant, Act 2 automatically switches to **replaying that SUMO run**: same night, same cars, streets, signals
  and seed, but the 1,000 app riders drive the routes the model picked.

This guide is the path from "the model returns routes" to "Act 2 shows them". Nothing here changes Act 1.

## Right now: a placeholder run

There is no model yet, so `demo/baseline.data.js` currently holds a **placeholder** `ml` variant: a real SUMO
run in which the app riders drive SUMO's default fastest routes, i.e. the baseline's routes. Every car has the
same start, end and requested time in both variants, as does the 6,000-car crowd. Only the routes are allowed to
differ, and for now they don't, so Act 2's numbers equal Act 1's. The video says so: the footnote, the
provenance line and the compare scene show `PLACEHOLDER`. It exists so the Act 2 UI can be polished on real data
shapes. It took ~7 min (build 11 s, both SUMO runs 2 min 45 s, replay export 3 min 40 s). How it was made (same inputs as Act 1's run):

```sh
RUN=fireworks-exodus-6k-placeholder-20260927T020939Z   # the run in demo/baseline.data.js now
demo/sumo/.venv/bin/python demo/sumo/kit.py build --placeholder \
  --scenario demo/sumo/data/demand-v3-seed42/scenario.json --net demo/sumo/data/network/sf.net.xml \
  --background demo/sumo/data/demand-v3-seed42/exodus-6000.rou.xml --radius 120 --end 14400 \
  --out demo/sumo/data/$RUN-bundle
# then steps 4-6 below with this $RUN
```

To swap in the model later, do steps 1–6: step 3 replaces `--placeholder` with `--ml <ml.json>`, and nothing
else changes. `check.mjs` fails if the two variants ever disagree on a rider's start, end or requested time.

```
ml/ + api/ running ──► ml_routes.py ──► ml.json ──► kit.py build --ml ──► kit.py run ──► view.py ──► baseline.data.js ──► index.html act 2
  (/plan answers)        (1,000 calls)              (map to SUMO roads)   (2 SUMO runs)  (replay + export)
```

## Before you start

- SUMO environment and network, as in [`sumo/README.md`](sumo/README.md) → Setup:
  `demo/sumo/.venv` with `eclipse-sumo==1.27.1 sumolib==1.27.1 pyproj==3.8.0`, and
  `demo/sumo/data/network/sf.net.xml`. Also `demo/sumo/.venv/bin/pip install rtree`: without it, matching
  1,000 routes to SUMO roads falls back to a brute-force search and takes much longer.
- The fireworks demand and crowd used by Act 1 (regenerate them if missing; both are seeded, so they come out
  byte for byte the same):
  ```sh
  PY=demo/sumo/.venv/bin/python
  $PY demo/sumo/kit.py scenario --out demo/sumo/data/demand-v3-seed42 --seed 42 --version 3
  $PY demo/sumo/kit.py background --scenario demo/sumo/data/demand-v3-seed42/scenario.json \
    --net demo/sumo/data/network/sf.net.xml --count 6000 --radius 120 \
    --out demo/sumo/data/demand-v3-seed42/exodus-6000.rou.xml
  ```
- `ml/` serving `POST /decide` ([`contracts/route_decision.md`](../contracts/route_decision.md)) and `api/`
  running with `ML_URL` pointing at it (`cd api && .venv/bin/uvicorn app.main:app`).

### The one thing that makes or breaks the "load balancer" story

The exporter calls `/plan?replay=true`, and **replay calls don't write `trips`**. So on its own, the model sees
each of the 1,000 riders alone and will likely send them all down the same "best" street, which is exactly the
baseline's problem. For the model to spread riders across routes, it has to know about the others: load
`demo/sumo/data/demand-v3-seed42/scenario.json` (every rider's origin, destination and departure) into
`ml/`'s demand context for this run, or have `ml/` count the routes it has already handed out for the same
time window. Never insert the synthetic riders into production MongoDB.

## 1. Smoke-test one request

```sh
head -1 demo/sumo/data/demand-v3-seed42/requests.jsonl        # {"trip_id": ..., "path": "/plan?..."}
curl -s "http://localhost:8000$(head -1 demo/sumo/data/demand-v3-seed42/requests.jsonl | python3 -c 'import json,sys;print(json.load(sys.stdin)["path"])')" \
  | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d["data"]["decision"], len(d["routes"][d["plan"]["best"]]["coords"]), "points")'
```

You want `ml:<model> <n> points`. `heuristic (...)` means `api/` couldn't use `ml/`; the reason is in the text.

## 2. Export the model's routes

```sh
demo/sumo/.venv/bin/python demo/sumo/ml_routes.py --demand demo/sumo/data/demand-v3-seed42 \
  --api http://localhost:8000 --out demo/sumo/data/ml-v3-<model>
```

- 1,000 `/plan` calls, one at a time. They can hit paid providers (Mapbox) the same way the app does.
- Every raw answer is appended to `<out>/responses.jsonl`. If the export stops (Ctrl-C, API restart), rerun the
  same command: it only asks for the trips that are still missing.
- `<out>/ml.json` is written only when **every** trip was decided by `ml/`. If some fell back to the
  heuristic, the script stops and names one. Fix `ml/`, delete those lines from `responses.jsonl`, and
  rerun. A heuristic route is never relabelled as ML.

## 3. Build the comparison bundle (no simulation yet)

Same network, crowd, seed, radius and horizon as Act 1's run; only the app riders' routes differ.

```sh
RUN=fireworks-exodus-6k-ml-$(date -u +%Y%m%dT%H%M%SZ)
demo/sumo/.venv/bin/python demo/sumo/kit.py build --ml demo/sumo/data/ml-v3-<model>/ml.json \
  --scenario demo/sumo/data/demand-v3-seed42/scenario.json --net demo/sumo/data/network/sf.net.xml \
  --background demo/sumo/data/demand-v3-seed42/exodus-6000.rou.xml --radius 120 --end 14400 \
  --out demo/sumo/data/$RUN-bundle
```

The build maps each route onto SUMO's roads and stops on the first one it can't use. Typical messages:

| Error | Meaning / fix |
|---|---|
| `ML geometry endpoint too far from requested OD` | The route doesn't start/end within 120 m of the rider. Check the API isn't snapping the origin somewhere else. |
| `Disconnected or forbidden turn` / `Route endpoint edges differ` | The polyline couldn't be followed on SUMO's network (sparse points, a road OSM/SUMO lacks). Export the full geometry, not waypoints. |
| `ML output belongs to a different scenario` | `ml.json` was made from another `scenario.json`. Re-export. |

**Known issue, not fixed yet.** Matching a map line onto SUMO's roads (`sumolib` `mapTrace` in
`kit.py build`) was tried on test lines that retrace the baseline's own roads: 95 of 100 riders came back
exactly right, and 5 failed with a disconnected turn. Those come from points snapped onto a nearby
junction's internal lanes, and from 0 m connector streets left by the OSM import. One failed rider stops the
whole build. Expect to fix this (e.g. splice the shortest legal connection across a gap of at most ~100 m)
once real `/plan` routes exist to test on. `kit.py` already drops junction-internal edges from the
match and searches 30 m around each point instead of 120 m, which is about 10× faster.

## 4. Run both variants in SUMO

```sh
demo/sumo/.venv/bin/python demo/sumo/kit.py run --bundle demo/sumo/data/$RUN-bundle \
  --out demo/sumo/runs/$RUN --sumo demo/sumo/.venv/bin/sumo
```

This runs the baseline again **and** the ML variant, as two separate SUMO processes with identical settings.
`demo/sumo/runs/$RUN/report.json` has completion counts and trip metrics for both, plus
`paired_mean_delta_seconds` (ML minus baseline, negative = faster). With this jammed scenario many trips
don't finish by 1 AM, so the run can end with
`SUMO failure/warnings: ... not eligible for a performance claim`. The report is still written; it only means
the full-cohort delta is left empty. Read `baseline.log` / `ml.log` if the exit wasn't clean for another reason.

## 5. Export the page data

```sh
cp demo/baseline.data.js demo/baseline.data.act1-only.js      # keep the current file, just in case
demo/sumo/.venv/bin/python demo/sumo/view.py --run demo/sumo/runs/$RUN \
  --replay demo/sumo/runs/$RUN-replay --sumo demo/sumo/.venv/bin/sumo --out demo/baseline.data.js
```

`view.py` replays both variants with per-second positions and refuses to export if anything differs from the
measured run. The file keeps its name, but now holds both `baseline` and `ml`, plus `ml_models` (the `ml:`
labels shown in the video). Expect roughly twice the current 5 MB.

## 6. Check and watch

```sh
node demo/check.mjs            # both variants vs report.json and summary.xml, second by second
python3 demo/sumo/check.py     # offline kit + exporter checks
open "demo/index.html?t=27"    # Act 2; ?t=51.5 for the side-by-side compare
```

## What changes in the video

Everything below comes from the data, so rerunning steps 2–5 with a better model updates the video by itself.

| Part | Concept mode (now) | With the ML run |
|---|---|---|
| Map, 27–49 s | toy model | the ML run on the real basemap, same camera and clock as Act 1, blue sweep at 27 s |
| Side panel | toy mph / AVs stopped | moving · stopped · can't pull out · arrived, adding up to all 7,000 cars |
| Chart | hidden | all cars in the ML run; dashed red line = where the baseline's "arrived" band was |
| Captions from 27 s | concept copy | same night / crowd leaves again / stopped vs. before at the baseline's worst second / arrived by 1 AM vs. baseline |
| Forecast bar, route-share panel | shown | hidden (they're toy-model numbers) |
| Compare, 51.5 s | right side = concept, "Next" | right side = ML run at the same second and camera, same four numbers as the left |
| Footnote / provenance | "illustrative model" | both panels SUMO, with the model labels |

The captions are the list spliced into `CAPTIONS` under `if (ML)` in `index.html`. Change the wording
there once real numbers are in. They state the numbers either way; if the model does worse than the baseline
the video will say so, which is what you want to find out before the pitch rather than during it.

## Handy

- Preview Act 2 without a model: no shortcut on purpose. A fake `ml` variant would put invented results in the
  video. To test the plumbing, make a throwaway `ml.json` in a temp folder (for example the baseline's own
  roads with an `ml:fixture` label), run steps 3–5 into temp paths, and delete them afterwards.
- `demo/sumo/data/` and `demo/sumo/runs/` are several GB; don't commit them.
- Background: [`sumo/README.md`](sumo/README.md) (kit details, ML import format, run semantics),
  [`SUMO_BASELINE_HANDOFF.md`](SUMO_BASELINE_HANDOFF.md) (baseline rules).

## Publish the video

Live copy: https://167-172-23-38.sslip.io/demo/ (Caddy serves `/srv/demo/` on the droplet at `/demo/*`; `tp-redeploy`
doesn't touch it). After step 6, upload the three files (needs the team's droplet SSH key):

```sh
scp demo/{index.html,replay.js,baseline.data.js} tp@167.172.23.38:/tmp/
ssh tp@167.172.23.38 'sudo mv /tmp/{index.html,replay.js,baseline.data.js} /srv/demo/'
```

## Quick recipe: rerun SUMO with our ML routes

With `ml/` and `api/` running (`ML_URL` set) and the SUMO setup from "Before you start":

```sh
PY=demo/sumo/.venv/bin/python; D=demo/sumo/data/demand-v3-seed42; RUN=fireworks-exodus-6k-ml-$(date -u +%Y%m%dT%H%M%SZ)
$PY demo/sumo/ml_routes.py --demand $D --api http://localhost:8000 --out demo/sumo/data/$RUN-ml
$PY demo/sumo/kit.py build --ml demo/sumo/data/$RUN-ml/ml.json --scenario $D/scenario.json \
  --net demo/sumo/data/network/sf.net.xml --background $D/exodus-6000.rou.xml --radius 120 --end 14400 \
  --out demo/sumo/data/$RUN-bundle
$PY demo/sumo/kit.py run --bundle demo/sumo/data/$RUN-bundle --out demo/sumo/runs/$RUN --sumo demo/sumo/.venv/bin/sumo
$PY demo/sumo/view.py --run demo/sumo/runs/$RUN --replay demo/sumo/runs/$RUN-replay \
  --sumo demo/sumo/.venv/bin/sumo --out demo/baseline.data.js
node demo/check.mjs && open "demo/index.html?t=27"
```

The riders, crowd, starts, ends and times stay identical to Act 1; only the app riders' routes change. If the
build stops on a route, see the known issue in step 3.
