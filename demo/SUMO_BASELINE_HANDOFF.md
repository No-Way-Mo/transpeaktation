# Handoff: redo the SUMO baseline and demo presentation

Use this note when another agent needs to rerun the **baseline-only** SUMO experiment and
refresh the presentation in `demo/index.html`. The ML comparison is a later task.

The experiment is a synthetic, reproducible cohort: 500 hardcoded SF origin/destination
requests, seed `42`, requested departures from **July 4, 2026 20:00–22:00 PDT**, and a
23:00 PDT drain horizon. The baseline is SUMO's fastest route on the imported OSM network.
It is not a measured July 4 traffic replay. The date supplies timestamps; it does not create
historical congestion.

## Run a fresh baseline

Work from the repository root. Do not reset or overwrite another agent's changes. First run
the small offline checks and record the scenario hash:

```sh
python3 demo/sumo/check.py
shasum -a 256 demo/sumo/data/demand/scenario.json
```

Use the existing `scenario.json` byte-for-byte. If it is missing, prepare the local SUMO
environment and regenerate it with seed 42, as described in [`sumo/README.md`](sumo/README.md):

```sh
python3.12 -m venv demo/sumo/.venv
demo/sumo/.venv/bin/pip install 'eclipse-sumo==1.27.1' 'sumolib==1.27.1' 'pyproj==3.8.0'
demo/sumo/.venv/bin/python demo/sumo/kit.py scenario \
  --out demo/sumo/data/demand --seed 42
```

The imported network must already be at `demo/sumo/data/network/sf.net.xml`. If it is not,
obtain an SF OSM XML extract and follow the `netconvert` instructions in the setup section
of the README. Keep the extract, `source.json`, import configuration, and `import.log` with
the run provenance.

Build and execute into new, timestamped paths. Never reuse `runs/baseline-first` or a prior
bundle:

```sh
RUN_ID="baseline-redo-$(date -u +%Y%m%dT%H%M%SZ)"
demo/sumo/.venv/bin/python demo/sumo/kit.py build --baseline-only \
  --scenario demo/sumo/data/demand/scenario.json \
  --net demo/sumo/data/network/sf.net.xml \
  --out "demo/sumo/data/${RUN_ID}-bundle" --radius 120

demo/sumo/.venv/bin/python demo/sumo/kit.py run \
  --bundle "demo/sumo/data/${RUN_ID}-bundle" \
  --out "demo/sumo/runs/${RUN_ID}" \
  --sumo demo/sumo/.venv/bin/sumo
```

Inspect `demo/sumo/runs/${RUN_ID}/report.json`, `execution.json`, `baseline.log`,
`baseline.tripinfo.xml`, `manifest.json`, and the archived inputs. Record the SUMO version,
scenario/network hashes, seed, endpoint radius, horizon, and command. Confirm every one of
the 500 cohort IDs is accounted for: completed, unfinished, not departed, failed/vaporized,
rerouted, or missing. A missing or unfinished trip is never a zero-duration success.

Report at least mean and p95 for departure delay, travel duration, waiting, SUMO time loss,
and distance, plus completion counts. Keep the full cohort visible; do not hide failures or
turn them into fake baseline wins.

## Refresh `demo/index.html`

The current HTML contains a separate deterministic canvas toy model in the inline
`<script id="sim">`. `demo/check.mjs` tests that toy model; it is not a SUMO result reader.
Keep the animation only if its copy clearly calls it illustrative. Do not silently present
its fabricated vehicle counts or speeds as measurements from `report.json`.

For the baseline presentation:

1. Replace the headline, captions, badges, and comparison values with the fresh SUMO report
   values. Use the report's actual completion/failure counts and mean/p95 metrics.
2. Present this as **SUMO baseline**: 500 synthetic users, seed 42, imported OSM network,
   no background vehicles, fixed routes, and no ML output.
3. Remove or clearly mark the `With transPEAKtation` side of the comparison as **ML pending**.
   Do not show an uplift, speed multiplier, or “more riders served” claim until a genuine ML
   bundle has been run with the same scenario, network, background demand, signals, horizon,
   and seed.
4. Keep the historical caveat visible: the July 4 timestamp and event inputs do not prove
   real July 4 congestion. PredictHQ attendance is an expectation, and 511/DataSF/WZDx
   closures are incident or planned-closure evidence, not measured surface-street speeds.
5. Add a compact provenance line or card containing the run ID, SUMO version, scenario hash,
   network snapshot, seed, horizon, endpoint radius, and whether background demand was used.

If the page still runs the toy animation, label its footer as illustrative and put the real
SUMO report metrics in a separate baseline card. Do not make the presentation read as though
SUMO replayed the live provider data. Preserve the existing visual language and keep the
change small; no API, MongoDB, Tiger, or new frontend dependency is needed for this handoff.

## Verification and handoff

Run these after the HTML edit:

```sh
node demo/check.mjs
python3 demo/sumo/check.py
git diff --check
open demo/index.html
```

Use a fresh output directory for every rerun, retain the old report, and include the new run
path and the exact metrics in the agent's handoff. Do not run production `/plan` calls, write
synthetic demand to MongoDB, write traffic to Tiger, or launch the ML comparison as part of
the baseline-only task.
