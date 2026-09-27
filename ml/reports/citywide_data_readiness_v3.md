# Citywide synthetic data v3: readiness for the large batch

Generated 2026-09-26T21:55:53+00:00 by `python -m eventsim.citywide_pipeline readiness`. **Data generation only; no model is trained.** All traffic is synthetic (SUMO) on the real SF road graph, with real permitted closures and dates. It is not observed traffic and not event ground truth.

## Verdict

**Ready to run.** The v3 verification batch passed the quality gate (16 runs) and preflight passed. Command below.

## The five problems: v2 benchmark vs v3 verification

| Problem | Fix (v3) | v2 (`b2_bench`) | v3.1 (`b31_verify`) |
|---|---|---|---|
| Parallel roads (Ocean Ave etc.) cause artificial jams and teleports | network v3 merges 127 parallel OSM edges into one edge carrying both carriageways' lanes | teleports/1k median 3.8, max 35.8; Ocean Ave hotspot 1761 | median 2.2, max 8.3; Ocean Ave hotspot 22 |
| Extreme event load overwhelms the network; ride-hail blocks lanes | event vehicles capped at 12,000; spreads widened so peak inflow ≤ 4,000 veh/h and outflow ≤ 5,000 veh/h; ride-hail stops pull off the lane | Folsom event: 58,956 trips, 2,113 teleports, 72 unfinished | Folsom event (12,000 veh, ±72 min): 51,215 trips, 251 teleports (4.9/1k), 1 unfinished |
| Mid-run closures leak (vehicles past the rerouting point) | rerouter triggers on every edge within 1500 m, so vehicles re-plan at their next edge after the closure opens | steady-state entries 3.0, onset 7.0 | steady 0.0, onset 2.0 |
| Unresolved closure mappings; closure pieces merged into junctions | review v3 (spacing-insensitive names; alleys/plazas with no drivable road); network v3 never absorbs accepted closure segments | 30 rows need review; 40 accepted segments absorbed | 0 rows need review (evidence CSV); 0 absorbed |
| Inputs are assumptions | public hours sourced; event demand from each event's attendance (API interface: `event_attendance_v1.csv`); all other demand as trip requests (origin/destination/time, the client format); network speeds checked against TomTom; signal regime varied (fixed/actuated) | 6/8 event hours assumed | see table below |

## Inputs: sourced vs assumed (v3)

| Input | Status | Evidence |
|---|---|---|
| folsom hours 11–18 | high confidence | https://www.folsomstreet.org/folsom-street-fair-1 |
| folsom attendance 275,000 | published figure (published figure) | organiser '275K+' https://www.folsomstreet.org/sponsorship (2026) |
| castro hours 11–18 | high confidence | https://castrostreetfair.org/fair/ |
| castro attendance 300,000 | published figure (published figure) | 300,000 (2007, low confidence) https://en.wikipedia.org/wiki/Castro_Street_Fair |
| portola hours 13–23 | medium confidence | doors 13:00 https://portolamusicfestival.com/general-info/ (23:00 end: search snippet) |
| portola attendance 42,000 | published figure (published figure) | 42,000/day (2024, Billboard/KTVU) https://en.wikipedia.org/wiki/Portola_Music_Festival |
| sunday_streets_excelsior hours 11–16 | medium confidence | 2025 hours https://www.sfmta.com/project-updates/sunday-streets-and-excelsior-festival |
| sunday_streets_excelsior attendance 15,000 | estimate (assumed range midpoint) | not found (range is an assumption) |
| bearrison hours 12–18 | high confidence | https://www.eventeny.com/events/bearrison-street-fair-29726/ |
| bearrison attendance 25,000 | published figure (published figure) | organiser '25K+' https://www.folsomstreet.org/sponsorship (2026) |
| halloween_cortland hours 16.5–20 | medium confidence | 2025 hours https://halloweenoncortland.com/halloween-on-cortland-spooky-fun-awaits/ |
| halloween_cortland attendance 6,000 | estimate (assumed range midpoint) | not found (range is an assumption) |
| chinatown_night_market hours 17–21 | high confidence | https://sf.funcheap.com/sfs-chinatown-night-market-returns-for-2026/ |
| chinatown_night_market attendance 15,000 | published figure (published figure) | 10,000-15,000 per market (2025, NBC Bay Area) https://www.nbcbayarea.com/news/local/san-franciscos-chinatown-night-markets-return/3865616/ |
| potrero_hill_festival hours 10–17 | high confidence | https://potrerofestival.com/ |
| potrero_hill_festival attendance 6,000 | estimate (assumed range midpoint) | not found (range is an assumption) |
| Non-event demand | trip requests (origin, destination, departure time) | synthetic stand-in requests saved per run (`runs/<run>/requests.parquet`); pass real client requests with `--requests` and they replace the stand-in one-for-one |
| Stand-in request volume | not identifiable from observed data yet | TomTom vs SUMO on 2026-09-26 hours [6, 7, 8]: sim/obs speed ratio 6000 vph→1.065, 10000 vph→1.066, 14000 vph→1.061, 18000 vph→1.059 (spread 0.007); speeds ~+6% vs TomTom at every level, so the network speed model agrees but early-morning demand can't be identified |
| Signal timing | assumption, varied | fixed 90 s cycles vs SUMO actuated control, sampled per family (no SF signal plans in the data) |
| Lane counts | assumption for 16,484 of 27,632 segments | OSM `lanes` where tagged, class defaults otherwise; no lane source for SF is pulled yet |
| Drive share, occupancy, ride-hail share, parking radius | assumption, varied | converts attendance to vehicles; recorded per family |
| Event vehicle cap 12,000 | assumption (parking/road capacity) | binds for the largest events; `vehicles_before_cap` recorded per family |
| Attendance for the other 108 verified events | category estimates | `prepared/event_attendance_v1.csv` (block party 300, farmers market 2,000, night market 10,000, …); the API replaces them |

## Verification batch (`b31_verify`)

| run_id | window | hours | trips | unfinished | not_inserted | teleports | teleports_per_1k | closed_entries_steady | closed_entries_onset | runtime_s | peak_rss_mb | quality_flag |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| folsom_arrival_f000_s0_event | arrival | 5.0 | 51215 | 1 | 0 | 251 | 4.9 | 0.0 | 0.0 | 2,284.2 | 725.5 | ok |
| folsom_arrival_f000_s0_control | arrival | 5.0 | 46212 | 0 | 0 | 59 | 1.3 | 0.0 | 0.0 | 1,987.7 | 714.8 | ok |
| castro_departure_f001_s0_event | departure | 5.0 | 70996 | 0 | 0 | 587 | 8.3 | 0.0 | 0.0 | 1,567.0 | 723.4 | ok |
| castro_departure_f001_s0_control | departure | 5.0 | 60200 | 0 | 0 | 187 | 3.1 | 0.0 | 0.0 | 1,201.7 | 702.0 | ok |
| portola_full_f002_s0_event | full | 12.8 | 151102 | 0 | 0 | 511 | 3.4 | 0.0 | 0.0 | 5,524.9 | 739.9 | ok |
| portola_full_f002_s0_control | full | 12.8 | 143931 | 0 | 0 | 256 | 1.8 | 0.0 | 0.0 | 5,252.4 | 734.9 | ok |
| sunday_streets_excelsior_arrival_f003_s0_event | arrival | 5.0 | 39306 | 0 | 0 | 56 | 1.4 | 0.0 | 0.0 | 1,518.3 | 735.4 | ok |
| sunday_streets_excelsior_arrival_f003_s0_control | arrival | 5.0 | 38578 | 0 | 0 | 37 | 1.0 | 0.0 | 0.0 | 1,285.6 | 728.8 | ok |
| bearrison_departure_f004_s0_event | departure | 5.0 | 49262 | 0 | 0 | 274 | 5.6 | 0.0 | 0.0 | 1,293.1 | 738.2 | ok |
| bearrison_departure_f004_s0_control | departure | 5.0 | 45217 | 0 | 0 | 62 | 1.4 | 0.0 | 0.0 | 1,083.1 | 727.4 | ok |
| halloween_cortland_full_f005_s0_event | full | 8.5 | 95360 | 0 | 0 | 230 | 2.4 | 0.0 | 2.0 | 3,673.5 | 724.9 | ok |
| halloween_cortland_full_f005_s0_control | full | 8.5 | 94564 | 0 | 0 | 152 | 1.6 | 0.0 | 0.0 | 3,514.9 | 723.1 | ok |
| chinatown_night_market_arrival_f006_s0_event | arrival | 5.0 | 44103 | 0 | 0 | 123 | 2.8 | 0.0 | 0.0 | 1,527.8 | 717.5 | ok |
| chinatown_night_market_arrival_f006_s0_control | arrival | 5.0 | 42969 | 0 | 0 | 95 | 2.2 | 0.0 | 0.0 | 1,434.1 | 715.5 | ok |
| potrero_hill_festival_departure_f007_s0_event | departure | 5.0 | 54218 | 0 | 0 | 117 | 2.2 | 0.0 | 0.0 | 1,256.5 | 718.7 | ok |
| potrero_hill_festival_departure_f007_s0_control | departure | 5.0 | 52968 | 0 | 0 | 98 | 1.9 | 0.0 | 0.0 | 1,099.4 | 714.8 | ok |

Gate: {"max_unfinished_share": 0.001, "max_teleports_per_1k": 10.0, "max_closed_entries_steady": 0, "max_review_runs_share": 0.0} → **passed**

## Large batch

- Plan: 8 events × 12 families × 2 seeds × (event + control) = 384 runs, windows rotating arrival / departure+recovery / full day.
- Estimated cost (from `b31_verify`): ~217.8 CPU-h → ~36.3 h wall at 6 workers, ~5.2 GB RAM, ~18.3 GB disk (69.7 GB free).
- Command (resumable; re-run the same line after an interruption):

```sh
cd ml && python -m eventsim.citywide_pipeline run --batch b3_main --families-per-event 12 --seeds 2 --workers 6
```

- Output: `ml/data/sf_citywide/batches/<batch>/export/sim_<run>.parquet` (canonical IDs, mph, 10-min UTC, congestion ratio, observed/closed/in_sumo masks, warmup/demand/drain phase, run/family IDs, synthetic=True), `segments.parquet` (per-segment gaps incl. merged_parallel), `quality.csv` (per-run quality_flag).

## Still open (does not block generation, limits realism)

- Real client requests don't exist yet: the stand-in request volume stays uncalibrated until requests or busier observed hours are available. To calibrate the stand-in against traffic, re-run `python -m eventsim.citywide_calibrate run --hours 12 13 14 17 18` later (sampler v3 then centres on it; calibration batches are frozen, so remove `batches/calib_v3` first or give a new day).
- 0 closure rows need a human decision: `prepared/closure_review_v3_needs_review.csv` (their cases stay out of the scenario pool).
- Attendance is organisers' claims or assumptions; lanes and signals are assumptions; no measured event traffic has validated any run (Folsom 2026-09-27 is the first chance).
