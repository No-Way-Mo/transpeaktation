# Citywide synthetic traffic data: readiness report

Generated 2026-09-26T15:21:07+00:00 by `python -m eventsim.citywide_batch readiness --batch b2_bench`. **Data generation only: no model has been trained.**

All traffic here is **synthetic** (SUMO), grounded in the real SF road graph, real permitted event closures and dates. Demand, attendance, timing, signal plans and driver behaviour are assumptions. Simulation does not create real event ground truth, and nothing here is observed traffic.

## Verdict

- **Pilot (v1, 4 runs): complete.** 0 unfinished, 0 not-inserted and 0 closed-road entries in all four runs; teleports 66–137 per run; roads with traffic in any run: 98.45% of physical street length.
- **Benchmark batch `b2_bench` (16/16 runs, 8 families, 8 events):** unfinished 72, not inserted 0, steady-state closed-road entries 3, teleports median 3.8 per 1,000 trips (worst 35.8: b2_bench_folsom_arrival_f000_s0_event).
- **Usable for:** relative event-vs-control effects on a shared citywide network (detours and spillover across neighbourhoods), with exact pairing of background trips. **Not usable as:** calibrated SF traffic levels, real event impacts, or ground truth.
- **Open problems:** 72 unfinished and 0 not-inserted trips in b2_bench; 3 steady-state closed-road entries in b2_bench; plus the network and demand gaps listed below.

## Coverage

- Canonical graph: 27,632 directed segments (3,129 km directed length).
- In SUMO: 26,730. Absorbed into merged junctions: 875 (9.9 km, median 11 m). Self-loops omitted: 27 (4.1 km). Unexplained omissions: 0. All are flagged per segment (`segments.parquet` → `gap`), never filled.
- Roads carrying traffic: pilot union 98.65% of directed length; benchmark median 26,084 segments per run. Empty buckets stay null (`observed=False`).
- Lanes: 16,484 segments use assumed lane counts; signal plans are all assumed (90 s cycles).

## Event locations (closure review v2)

- 1,105 special-event closure rows / 184 permit cases. Row decisions: {'accept': 715, 'reject': 339, 'needs_review': 30, 'partial_restriction': 21}. Case status: {'verified': 109, 'unverified': 71, 'partial': 4}.
- Accepted by rule, with reasons kept per row in `prepared/closure_review_v2.json` (the v1 matches are unchanged): undefined direction on all-lanes closures (both directions closed); unnamed links with ≥90% overlap; closures shorter than one same-named edge (whole edge closed, conservative, e.g. Folsom's Langton St row, which the v1 pilot left open); remainders with no drivable road under them (17th St at Castro = Jane Warner Plaza).
- 30 rows still need a human decision (mostly no same-named edge under the line). Cases with any such row are not used as scenario locations.
- 40 of 735 accepted closure segments are junction connectors absorbed into merged junctions: those short pieces can't be closed or measured in SUMO (the adjacent closed blocks are).
- Only `verified` cases are used. Public hours are sourced for Castro and Folsom; for the other events they are an assumption inside the permit window.

## Quality problems investigated

- **Teleports (pilot, reproduced exactly with warnings on):** 192 teleports at 38 junctions; top 10 junctions = 74.0%; reasons {'yield': 165, 'jam': 26, 'wrong lane': 1}; at event closures: 0.
  - 117 of them (61%) are on one ~250 m stretch of Ocean Ave (Miramar/Faxon/Capitol), where OSM draws two parallel carriageway edges between the same nodes (e.g. ways 679078809 and 1494530502). 126 such parallel pairs exist citywide. Not fixed yet; see gaps.
- **Bus-only roads open to cars (fixed for batches):** 264 segments are `highway=busway` or `access=no` (Van Ness BRT, Transbay Bus Ramp, …). The v1 pilot let cars use them (~0.7% of simulated vehicle-km). Batch schema v2 bakes them out of each run's network (`segments.parquet` → `car_access`).
- **Closure onset:** mid-simulation closures (SUMO rerouters) can still admit vehicles already committed past the last upstream trigger in the first 20 min; reported separately (`closed_entries_onset`).
- **Runs flagged `review` (2 of 16):** rule = any unfinished/not-inserted trip, > 10 teleports per 1,000 trips, or steady-state closed-road entries. Flagged runs are kept and exported with the flag in `quality.csv` and the export manifest; they are not deleted or re-planned.
  - `b2_bench_folsom_arrival_f000_s0_event`: 2113 teleports (35.8/1k, peaking 11:00–12:00 local) and 72 unfinished trips: event-induced overload. 25,000 event vehicles (assumed attendance 230,471 × drive share 0.29, at the cap) arrive with a ±38-min spread, and ride-hail stops block a travel lane. Teleports delete the queues, so this run is not trustworthy even though it finished.
  - `b2_bench_sunday_streets_excelsior_arrival_f003_s0_event`: 3 vehicles entered a closed edge 20–30 min after a mid-window closure opened (queue already past the last rerouter trigger): the onset transient, slightly longer on a busy arterial.
- **Fixed during the benchmark:** evening events with late arrivals crashed departure sampling; batch runs used the pilot's family table when extracting. Both are covered by unit tests now.

## Scenario inventory: `b2_bench`

Each family: 1 seed variant here, each an event run + a no-event control with identical background trips. `family_id` and `family_group` (event) are kept for later grouped splits.

| family | event | date | window | local | bg peak vph | OD | event veh | event closures | concurrent closures | hours source |
|---|---|---|---|---|---|---|---|---|---|---|
| folsom_arrival_f000 | folsom | 2026-09-27 | arrival | 8.5–13.5 h | 9037 | arterial | 25000 | 55 | 28 | sourced |
| castro_departure_f001 | castro | 2026-10-04 | departure | 16.0–21.0 h | 4491 | uniform | 5317 | 16 | 6 | sourced |
| portola_full_f002 | portola | 2026-09-27 | full | 10.0–23.8 h | 11261 | arterial | 847 | 15 | 68 | assumed |
| sunday_streets_excelsior_arrival_f003 | sunday_streets_excelsior | 2026-10-18 | arrival | 8.5–13.5 h | 12988 | downtown | 1237 | 28 | 13 | assumed |
| bearrison_departure_f004 | bearrison | 2026-10-17 | departure | 16.0–21.0 h | 4285 | arterial | 528 | 7 | 14 | assumed |
| halloween_cortland_full_f005 | halloween_cortland | 2026-10-31 | full | 15.0–23.0 h | 3596 | arterial | 848 | 7 | 40 | assumed |
| chinatown_night_market_arrival_f006 | chinatown_night_market | 2026-10-09 | arrival | 15.5–20.5 h | 10757 | downtown | 1051 | 6 | 6 | assumed |
| potrero_hill_festival_departure_f007 | potrero_hill_festival | 2026-10-17 | departure | 15.0–20.0 h | 9433 | downtown | 778 | 4 | 17 | assumed |

Varied per family: event location/date (verified permits), time window (arrival / departure + 3 h recovery / full day), background peak demand, hourly profile (weekend/weekday), local-trip share and radius, OD weighting (uniform / arterial / downtown), attendance × drive share ÷ occupancy × turnout → event vehicles (capped at 25,000), ride-hail share and curb dwell, arrival offset/spread, departure surge share/sharpness, parking radius, origin distance decay, driver and rerouting parameters, seed. Other verified closures active that day are applied to both runs of a pair.

## Benchmark quality and cost

| run_id | window | hours | trips | unfinished | not_inserted | teleports | teleports_per_1k | closed_entries_steady | closed_entries_onset | segments_with_traffic | runtime_s | peak_rss_mb | disk_mb | quality_flag |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| folsom_arrival_f000_s0_event | arrival | 5.0 | 58956 | 72 | 0 | 2113 | 35.8 | 0.0 | 0.0 | 26076 | 2,663.8 | 805.8 | 19.1 | review |
| folsom_arrival_f000_s0_control | arrival | 5.0 | 32981 | 0 | 0 | 112 | 3.4 | 0.0 | 0.0 | 26053 | 568.8 | 710.6 | 11.3 | ok |
| castro_departure_f001_s0_event | departure | 5.0 | 18164 | 0 | 0 | 86 | 4.7 | 0.0 | 0.0 | 25706 | 371.6 | 712.4 | 7.8 | ok |
| castro_departure_f001_s0_control | departure | 5.0 | 14885 | 0 | 0 | 58 | 3.9 | 0.0 | 0.0 | 25573 | 296.7 | 703.6 | 6.7 | ok |
| portola_full_f002_s0_event | full | 13.8 | 113605 | 0 | 0 | 422 | 3.7 | 0.0 | 0.0 | 26103 | 2,070.2 | 714.8 | 38.1 | ok |
| portola_full_f002_s0_control | full | 13.8 | 111919 | 0 | 0 | 369 | 3.3 | 0.0 | 0.0 | 26128 | 1,960.8 | 713.1 | 37.5 | ok |
| sunday_streets_excelsior_arrival_f003_s0_event | arrival | 5.0 | 39920 | 0 | 0 | 217 | 5.4 | 3.0 | 7.0 | 26135 | 997.4 | 726.9 | 13.7 | review |
| sunday_streets_excelsior_arrival_f003_s0_control | arrival | 5.0 | 38808 | 0 | 0 | 183 | 4.7 | 0.0 | 0.0 | 26140 | 954.0 | 722.1 | 13.3 | ok |
| bearrison_departure_f004_s0_event | departure | 5.0 | 16093 | 0 | 0 | 61 | 3.8 | 0.0 | 0.0 | 25465 | 314.9 | 704.4 | 6.9 | ok |
| bearrison_departure_f004_s0_control | departure | 5.0 | 15660 | 0 | 0 | 70 | 4.5 | 0.0 | 0.0 | 25408 | 310.7 | 702.7 | 6.7 | ok |
| halloween_cortland_full_f005_s0_event | full | 8.0 | 22236 | 0 | 0 | 108 | 4.9 | 0.0 | 0.0 | 25789 | 603.5 | 710.6 | 10.4 | ok |
| halloween_cortland_full_f005_s0_control | full | 8.0 | 20540 | 0 | 0 | 100 | 4.9 | 0.0 | 0.0 | 25709 | 532.7 | 707.1 | 9.7 | ok |
| chinatown_night_market_arrival_f006_s0_event | arrival | 5.0 | 44265 | 0 | 0 | 108 | 2.4 | 0.0 | 0.0 | 26174 | 802.1 | 715.0 | 14.2 | ok |
| chinatown_night_market_arrival_f006_s0_control | arrival | 5.0 | 43961 | 0 | 0 | 109 | 2.5 | 0.0 | 0.0 | 26181 | 741.9 | 713.3 | 14.0 | ok |
| potrero_hill_festival_departure_f007_s0_event | departure | 5.0 | 35564 | 0 | 0 | 107 | 3.0 | 0.0 | 0.0 | 26093 | 587.0 | 712.8 | 12.2 | ok |
| potrero_hill_festival_departure_f007_s0_control | departure | 5.0 | 34896 | 0 | 0 | 123 | 3.5 | 0.0 | 0.0 | 26097 | 449.7 | 710.8 | 12.0 | ok |

- Runtime ≈ 3.54 ms per (trip × simulated hour); median 116 s per simulated hour. Peak memory per SUMO run: 806 MB max. Disk per run (compact outputs, raw XML dropped): 12.1 MB + 7.8 MB parquet export. Raw XML would add ~27 MB per simulated hour.
- **Estimate for 100 families × 2 seeds × 2 = 400 runs:** ~105.4 CPU-hours → ~17.6 h wall at 6 workers, ~4.7 GB RAM, ~7.8 GB disk (mean window 6.5 h, mean 41,403 trips/run as in b2_bench). This machine has ~86 GB free disk, so keep raw XML off (`--keep-raw` only for diagnosis).

## Normalized exports

- `ml/data/sf_citywide/batches/b2_bench/export/sim_<run_id>.parquet`: dense segment × 10-min UTC bucket grid. Canonical `road_segment_id` (OSM u-v-key), `speed_mph`, `free_flow_speed_mph` (posted-limit fallback), `congestion_ratio`, `travel_time_s`, volumes, masks `observed` / `closed` / `in_sumo`, `phase` (warmup/demand/drain), and `run_id`, `family_id`, `family_group`, `batch`, `with_event`, `seed`, `window`, `synthetic=True`, `source=sumo_synthetic`.
- `…/b2_bench/export/segments.parquet`: per-segment gaps, car access, free-flow and lane sources, provider geometry flags. `…/manifest.json`: schema notes.
- v1 pilot: `ml/data/sf_citywide/export/simulation_observations_<run>.csv.gz` (observed rows only).
- Scenario/provenance: `…/scenarios.json` (sourced vs assumed per family), `runs/<run>/summary.json`, `teleports.csv`, `quality.csv`, `teleport_hotspots.csv`.
- Offline files only. They must never be loaded into observed `traffic_metrics`.

## Remaining gaps before a large batch

1. Parallel OSM edges (126 pairs), led by Ocean Ave: merge or drop the duplicate carriageway in a v3 network, then re-run the teleport diagnosis.
2. 30 closure rows need a human decision; 71 cases are unverified and 4 partial. Only 8 of 109 verified cases are in the scenario pool (the rest are mostly small block parties and markets).
3. Demand is uncalibrated: no citywide OD or counts. A first sanity check would compare simulated speeds with the TomTom/Mapbox polling at the same hour (units only, not calibration).
4. Public hours are assumed for 6 of 8 events, and attendance is assumed for all of them.
5. Event load: cap event vehicles per window well below 25,000, or spread arrivals, and give ride-hail stops off-lane curb space (SUMO `parkingArea` / `parking="true"`) before the large batch. Keep `review`-flagged runs out of training by default.
6. Signal timings (90 s everywhere) and 60% of lane counts are assumed.
7. Closures on absorbed junction connectors aren't enforceable; mid-run closures have an onset transient.
8. No real-event validation exists. Folsom 2026-09-27 is the first chance if the poller keeps running.

Stop point: data generation and quality checks only. No windowing, split assignment or model training was done.
