# July 4 SUMO comparison kit

Run from the repository root. **Nothing runs SUMO except the explicit `run` command.**
Offline check: `python3 demo/sumo/check.py`.

500 distinct synthetic users each book one trip between hardcoded SF locations. Seed 42
fixes the OD assignments and requested departures in **July 4, 2026 20:00–22:00 PDT**
(America/Los_Angeles; July 5 03:00–05:00 UTC). They are local scenario records, not real
accounts, bookings, payments, or production `trips` writes. Default horizon is 23:00 PDT:
7200 seconds of admissions plus 3600 seconds to drain. Unfinished trips remain visible.

This is a synthetic experiment, not a historical July 4 replay or evidence of peak traffic.
The date supplies request timestamps; it does not generate crowds, closures, or congestion.
500 cars over two hours may produce little congestion. OSM topology, speed limits, guessed
signals and SUMO default driving behavior need calibration against observed traffic before
making real-world claims. No calibrated July 4 inputs or ML results are bundled.

## Completed baseline demo

Executed on September 26, 2026 with SUMO 1.27.1, seed 42, the original 500-user demand,
120 m endpoint snap limit, and no background vehicles. All 500 completed; zero unfinished,
not-departed, failed or missing trips. SUMO exited 0 with no runtime warnings. The map
import did produce warnings about inferred signals, geometry, and ambiguous restrictions;
these are retained in `data/network/import.log` and limit real-world interpretation.

| Metric | Mean | p95 |
|---|---:|---:|
| Travel duration | 14.23 min | 26.23 min |
| Departure delay | 0.106 sec | 0 sec |
| Waiting time | 7.21 min | 15.85 min |
| SUMO time loss | 9.41 min | 18.99 min |
| Route distance | 5.69 km | 9.65 km |

Last arrival: **22:24:25 PDT** (simulation second 8665). Waiting/time loss includes the
imported signal behavior; these numbers are not measured holiday congestion. No ML
comparison has been run. Full results: [`runs/baseline-first/report.json`](runs/baseline-first/report.json).
Inputs, software version, native configurations and raw trip records remain in that run directory.

The prepared graphical entrypoint is `runs/baseline-first/demo.sumocfg`; it uses relative
input paths, a 20 ms animation delay and timestamped output names to preserve measured results.
After installing XQuartz on this Mac, open it with:

```sh
demo/sumo/.venv/bin/sumo-gui -c demo/sumo/runs/baseline-first/demo.sumocfg
```

## Waterfront 1K cohort and the replay page (`demo/baseline.html`)

`kit.py scenario --version 2` writes 1000 synthetic users (seed 42) that start or end at the northern
waterfront and downtown (Marina, Marina Green, Fort Mason, Ghirardelli, Wharf, Pier 39, North Beach,
Chinatown, Union Square, Ferry Building): 50% home to busy place, 35% busy to busy, 15% busy to home.
Version 1 (the 500-user cohort above) is unchanged. Executed September 26, 2026:
`runs/waterfront-1k-20260926T210806Z`, scenario sha256 `3b8ad9e6…a5e005`, radius 120 m, no background.
All 1000 completed; travel 11.3 min mean / 23.4 p95, waiting 5.2 / 13.3 min, time loss 6.9 / 16.6 min.

```sh
demo/sumo/.venv/bin/python demo/sumo/kit.py scenario --out demo/sumo/data/demand-v2-seed42 --seed 42 --version 2
# then build --baseline-only / run as above into new directories, and export the page data:
demo/sumo/.venv/bin/python demo/sumo/view.py --run demo/sumo/runs/<run> --replay demo/sumo/runs/<run>-fcd \
  --sumo demo/sumo/.venv/bin/sumo --out demo/baseline.data.js
```

`view.py` reruns the run's exact command with per-second position output and refuses to export unless
every trip matches the measured tripinfo and SUMO's waiting seconds; `node demo/check.mjs` then checks
the page's numbers against report.json. With 1000 cars and no background traffic, delays are signal
waits and local queues, not citywide gridlock; add identical `--background` vehicles to both variants
for heavier traffic.

## Fireworks exodus, 21:00-01:00 (`demo/baseline.html`)

`kit.py scenario --version 3` writes 1000 app users for 21:00-23:00 PDT: 25% drive to a viewing site
(Golden Gate overlook on Lincoln Blvd, Crissy Field, Marina Green, Fort Mason, Ghirardelli, Wharf, Pier 39)
before the 21:30 show (PredictHQ: "Fourth of July fireworks on Golden Gate Bridge", 300,000 predicted
attendance), 75% leave one 21:45-22:45. `kit.py background --count N` writes N identical non-app crowd
cars leaving those sites 21:45-22:45, parked on ordinary streets within `--spread` (400 m) of each site.
**N is an assumption**; no measured exit count exists. Build with `--background` and `--end 14400`.

Executed September 26, 2026 with N = 12,000: `runs/fireworks-exodus-12k-spread-20260926T213340Z`.
App users: 385 completed, 245 still on the road at 01:00, 370 never got onto the road; completed trips
averaged 35.0 min (p95 115.7). Crowd: 2,308 arrived, 6,122 still on the road, 3,570 never started. SUMO
exited cleanly; the jam is from demand exceeding what SUMO's junction model and OSM-guessed signals
pass, with no teleporting. Real traffic control (officers, closures incl. the Golden Gate Bridge) is not
modeled, so clearance time is not a prediction. `runs/fireworks-exodus-12k-20260926T212821Z` is the
earlier variant with crowd cars starting on only seven edges (kept for comparison).

`demo/baseline.html` uses N = 6,000 (`runs/fireworks-exodus-6k-20260926T214929Z`): app users 507 completed,
397 still on the road at 01:00, 96 never got onto the road; completed trips averaged 39.4 min (p95 132.3).
All 7,000 cars at 01:00: 2,504 arrived, 3,754 on the road (3,645 stopped), 742 unable to pull out.

`view.py` records app-user positions, SUMO `--summary-output` (all cars per second) and `edgeData`
(`speedRelative` per road per minute) in a replay of the exact run command, then checks them against
tripinfo. The page treats all cars as one group: its trip results come from `kit.summarize` over every car, and the side panel's groups (moving, stopped, can't pull out, arrived, not leaving yet) are
checked to add up to every car each second. With `--tripinfo-output.write-unfinished`, SUMO marks cars still running or never inserted at
the horizon `vaporized="end"`; `summarize` counts those as unfinished / not departed, not failed.

## Fetch historical inputs without running SUMO

The read-only July 4 DataSF backfill, optional PredictHQ historical event snapshot, 511
archived-event pull, and Tiger/Mongo inspection commands are in
[`HISTORICAL_INPUTS.md`](HISTORICAL_INPUTS.md). The source audit found no stored traffic
speed rows for the target UTC window in this worktree, so the prepared baseline remains a
synthetic OSM free-flow experiment. The historical runbook deliberately keeps event and
closure evidence separate from measured traffic.

After credentials were supplied, the historical pulls returned 146 PredictHQ records (30
overlapping the target window, including a 300,000-attendance fireworks prediction), zero
511 archived traffic events in the exact target window, and 552 current WZDx features (133
with schedules that overlap the target; the feed update was September 26, so these are not a
historical speed replay). A bounded live poll also succeeded for Mapbox Directions, Mapbox
tiles, TomTom flow tiles, Muni positions, and current 511 events; those observations are
September 26 data and are not substituted for July 4 measurements.

## Run the baseline first (no ML required)

The kit now supports a baseline-only bundle. With the local environment and network ready,
run these commands from this worktree's repository root:

```sh
demo/sumo/.venv/bin/python demo/sumo/kit.py build --baseline-only \
  --scenario demo/sumo/data/demand/scenario.json \
  --net demo/sumo/data/network/sf.net.xml \
  --out demo/sumo/data/baseline-bundle --radius 120

demo/sumo/.venv/bin/python demo/sumo/kit.py run \
  --bundle demo/sumo/data/baseline-bundle \
  --out demo/sumo/runs/baseline-first \
  --sumo demo/sumo/.venv/bin/sumo
```

Choose a **new** output directory when repeating either command. The run writes
`report.json`, `baseline.tripinfo.xml`, `baseline.log`, `execution.json`, archived inputs,
and `baseline.sumocfg`. Baseline-only reports contain no ML comparison or claimed uplift.
The initial cohort remains unchanged: 500 users, seed 42, no background traffic.
This network needs `--radius 120`: the Oracle Park coordinate is 101.9 m from its
nearest passenger edge; all other locations are within 45.1 m. Use the same radius
for the later ML bundle. The OSM extract reports a June 1, 2026 snapshot; see
`data/network/source.json` and `data/network/import.log` for provenance/import warnings.

For the visual demo, reopen the native configuration (this runs the same simulation again):

```sh
demo/sumo/.venv/bin/sumo-gui -c demo/sumo/runs/baseline-first/baseline.sumocfg \
  --output-prefix TIME-gui- --delay 20
```

Press Play in SUMO to start. The output prefix protects the measured run's tripinfo.
On macOS the GUI requires XQuartz, which was not installed on this machine during the
headless run. Install it with `brew install --cask xquartz`; activation may require a new
login session (see the [SUMO macOS instructions](https://sumo.dlr.de/docs/Installing/index.html)).
The headless runner already works without it. For a fresh measured
run use `kit.py run` with a new output directory instead of replaying the saved config.
Keep this network and scenario for the later ML comparison; build a new combined bundle
with `--ml` and run both variants again under identical settings.

## Setup

Python 3.10+ is sufficient for the scenario/check. For network preparation and execution,
install SUMO using its [official installation guide](https://sumo.dlr.de/docs/Installing/index.html).
The local install below provides `sumo`, `sumo-gui` and `netconvert`. Install matching Python `sumolib` plus `pyproj`
(the geographic projection dependency) into a local environment; use the same SUMO version
on all comparisons, record/pin the version in your experiment notes:

```sh
python3.12 -m venv demo/sumo/.venv
# Local binaries and matching library; no system-wide install required.
demo/sumo/.venv/bin/pip install 'eclipse-sumo==1.27.1' 'sumolib==1.27.1' 'pyproj==3.8.0'
python3 demo/sumo/kit.py scenario --out demo/sumo/data/demand --seed 42
```

This exports `scenario.json` and 500 **unexecuted** `/plan?replay=true` request paths in
`requests.jsonl`. Keep the scenario file byte-for-byte unchanged; its SHA-256 ties ML
output to the cohort. Use a different output directory for every preparation/run.

Obtain an OSM XML extract (`sf.osm.xml`) covering all SF and a margin, e.g. bounding box
west=-122.53, south=37.70, east=-122.35, north=37.84. Use an OSM export/Overpass download
or an existing licensed extract; retain its source URL, download/snapshot date, and hash.
For historical claims you need a suitable historical snapshot and observed closures too.
Do not pass a PBF directly to this command. See SUMO's
[OSM import guide](https://sumo.dlr.de/docs/Networks/Import/OpenStreetMap.html).

```sh
mkdir -p demo/sumo/data/network
# Put your OSM XML at demo/sumo/data/network/sf.osm.xml first.
demo/sumo/.venv/bin/netconvert --osm-files demo/sumo/data/network/sf.osm.xml \
  --output-file demo/sumo/data/network/sf.net.xml \
  --geometry.remove --ramps.guess --junctions.join --tls.guess-signals --tls.join \
  --keep-edges.by-vclass passenger \
  --save-configuration demo/sumo/data/network/import.netccfg
# Saving a native configuration exits without importing; execute it separately.
demo/sumo/.venv/bin/netconvert -c demo/sumo/data/network/import.netccfg
```

Keep the import configuration/logs and source extract with the experiment. Map import is
preparation, not a traffic simulation. Inspect the resulting network/signals before use.

## Supply ML routes later

The kit imports a single JSON file. It deliberately has no HTTP fetch command, database
client, or dependency on unpublished API changes. An exporter can call the public API
using `requests.jsonl` **later**, against a local/test deployment with the real ML model
configured. Those calls may use paid upstream routing/text providers. The committed API
accepts `from` and `to` as `lon,lat`, and `depart_at` with offset. Its historical window is
limited to one year back; after that, use archived output or a suitable isolated adapter.

For each response, require `data.decision` to start with `ml:`; take the **final** geometry
from `routes[plan.best].coords` (API order **lat,lon**). A waypoint-based `/decide` response
is not final road geometry: `/plan` asks the provider for that geometry. A heuristic fallback
must not be relabeled ML. Preserve raw responses, model revision/config, data snapshot and
provider provenance alongside the import file. The label is a provenance assertion by the
exporter, not cryptographic proof that a model ran.

The import shape is below (illustrative only; provide all 500 real routes):

```json
{
  "coordinate_order": "lat,lon",
  "scenario_sha256": "SHA256_OF_SCENARIO_JSON",
  "routes": [
    {
      "trip_id": "user-0000",
      "depart_at": "EXACT_depart_at_FROM_THIS_TRIP_IN_SCENARIO",
      "decision": "ml:MODEL_VERSION",
      "coords": [[37.7599, -122.4194], [37.7880, -122.4075]]
    }
  ]
}
```

Get the hash with `shasum -a 256 demo/sumo/data/demand/scenario.json`. Export the full
polyline (including bends), not just OD points or ML waypoints. Ordering of route records
is irrelevant; IDs must match exactly, once each. Extra provenance fields are retained.
`scenario.json` is also the demand export for the model: replay requests do **not** log trips,
so 500 replay calls do not make the model aware of these 500 users. Load the scenario into
an isolated model demand context, or document that routing used no synthetic cohort demand.
Do not insert synthetic demand into production MongoDB. See
[`contracts/route_decision.md`](../../contracts/route_decision.md).

## Build and inspect (no simulation)

```sh
demo/sumo/.venv/bin/python demo/sumo/kit.py build \
  --scenario demo/sumo/data/demand/scenario.json \
  --net demo/sumo/data/network/sf.net.xml \
  --ml demo/sumo/data/ml.json \
  --out demo/sumo/data/bundle --end 10800
```

Baseline is **SUMO free-flow fastest routing on imported OSM**, not OSRM, Mapbox, or the
API's heuristic. Both variants use exactly the same nearest passenger-allowed endpoint
edges and full endpoint-edge traversal (`departPos=0`, `arrivalPos=max`). This coarse curb
snapping can move endpoints along a long edge; inspect `matching.json` and route XML in
SUMO's network tools. Upgrade to calibrated curb positions if that error matters.

API OSMnx `u-v-key` IDs are not SUMO IDs. The kit converts geographic geometry with the
network projection and uses native [sumolib mapTrace](https://sumo.dlr.de/pydoc/sumolib/route.html),
then rejects disconnected turns, passenger-forbidden edges, and mismatched endpoint edges.
Matching is approximate, especially on parallel roads; visual route review remains necessary.
A fixed nearest-edge tie break avoids using ML routes to choose baseline endpoints. A bad
snap/disconnected network aborts the whole bundle: investigate or explicitly change `--radius`
(default 60 m) and rebuild into a new directory; never silently drop a difficult user.
An interrupted/failed build has no manifest and cannot run.

Optional `--background path/to/background.rou.xml` copies **identical fixed background
vehicles** into both runs. Only this deliberately narrow format is accepted:

```xml
<routes>
  <vehicle id="bg-0001" depart="0"><route edges="SUMO_EDGE_A SUMO_EDGE_B"/></vehicle>
</routes>
```

Use unique `bg-` IDs, departure seconds in [0,7200), ascending departure order, and inline
connected passenger routes on this network. No flows, external references, custom types,
rerouters or probabilistic route distributions. Background uses SUMO's default passenger
type in both runs. Its interactions will differ as experimental routes differ; its demand,
network and seed do not. No background means only the 500 experimental vehicles.
Closures must be baked consistently into the supplied network; the kit does not infer them.

## Explicit later execution

**These commands start simulations. A combined run requires genuine ML output.**

```sh
demo/sumo/.venv/bin/python demo/sumo/kit.py run \
  --bundle demo/sumo/data/bundle --out demo/sumo/runs/seed42-first \
  --sumo demo/sumo/.venv/bin/sumo
```

For a combined bundle, the runner launches separate baseline and ML processes with the same network, signals,
demand, seed, horizon, vehicle settings and background. Routes stay fixed; automatic
rerouting and teleporting are disabled. Pending insertion is not discarded. Input hashes
are checked, inputs are archived per run, and an existing output directory is never reused.
A run retains route inputs, manifest, commands, SUMO version, console logs and tripinfo XML.
For a repeated deterministic run use a new output path. For seed sensitivity regenerate a
scenario with a new seed, obtain its ML routes and rebuild; compare within each seed first.

`report.json` contains completion, unfinished, not-departed, failed/vaporized/rerouted and
missing counts for **all 500 users**, plus mean and nearest-rank p95 departure delay, travel
duration, total requested-departure-to-arrival time, waiting, time loss (seconds), and distance
(metres) for completed trips. Background trips are excluded from cohort metrics.
See [SUMO tripinfo semantics](https://sumo.dlr.de/docs/Simulation/Output/TripInfo.html).
A paired completed-only delta (ML minus baseline) is descriptive and may have survivor bias.
The full-cohort delta is null unless every user completes in both variants and both runs exit
cleanly without SUMO warnings. Inspect failures/logs; a missing or unfinished trip is never a
zero-duration win. Use a longer common `--end` in a fresh bundle if the drain is insufficient.

Offline checks cover determinism, time conversion, ML identifiers/geometry guards, route
connectivity guards, overwrite refusal and failure-aware metrics. They do not establish that
an external SF network or ML route set is valid: those are checked during later build/run.
