# Proposal: road forecast contract (ml → api / fleet optimizer)

**Status: proposal only.** Nothing under `contracts/`, `api/`, `ingest/` or `web/` has been changed, and no forecast is
written to MongoDB or Tiger. The contracts rule in `AGENTS.md` still applies: this goes in its own small PR after
the team has agreed to it.

## Why the existing `prediction_metrics` table is not enough

`prediction_metrics(time, model_version, event_id, road_segment_id, prediction_horizon_min, current_speed_mph,
predicted_speed_mph, predicted_delay_sec, predicted_demand, confidence)` has these gaps:

| Need | Gap in `prediction_metrics` |
|---|---|
| Know which interval a value is for | only `time` + horizon; the issue time vs valid interval is ambiguous |
| Closed / not-modelled roads | no availability field, so a missing row looks the same as "free flow" |
| Explicit fallbacks | no `prediction_source` (model / representative road / fallback) |
| Honest uncertainty | `confidence` would be filled with invented numbers. It must stay NULL until an uncertainty method has been evaluated |
| Provenance | no network version, dataset id or synthetic-training flag |
| Separation of concerns | `predicted_demand` belongs to the demand model; this forecaster never predicts demand |

## Proposed shape: `road_forecast` (one row per road × issue time × horizon)

| Field | Type | Meaning |
|---|---|---|
| `road_segment_id` | text | canonical OSM `u-v-key` (= Mongo `road_segments.segment_id`) |
| `issued_at` | timestamptz | end of the last completed 10-min history bucket |
| `valid_from`, `valid_to` | timestamptz | `[issued_at + 10(k-1) min, issued_at + 10k min)` |
| `horizon_min` | int | 10, 20, 30, 40, 50, 60 |
| `predicted_travel_time_sec` | float, null | primary output; null unless availability is open/restricted-partial |
| `predicted_speed_mph` | float, null | `length_m / travel_time`: derived, never predicted separately |
| `predicted_congestion_ratio` | float, null | `clip(1 - speed / free_flow, 0, 1)`: derived |
| `availability` | enum | `open` · `closed` (a known closure covers the whole bucket) · `restricted` (partial-bucket closure, or passenger access barred) · `unavailable` (not represented in the model network) |
| `restriction_reason` | text | `none`, `scheduled_closure`, `partial_closure_see_closures_table`, `no_passenger_access`, `merged_parallel`, `not_modelled:<gap>` |
| `prediction_source` | enum | `model` · `representative_road` (explicit mapping, `represented_by` set) · `none` |
| `represented_by` | text, null | the road whose prediction was copied (v3 merged parallel carriageways) |
| `model_version`, `network_version`, `dataset_id` | text | provenance keys |
| `training_source` | text | e.g. `sumo_synthetic:b3_verify`: says the model was trained on synthetic data |
| `input_source` | text | provenance of the history snapshot (live feed vs `sumo_synthetic`) |
| `synthetic_training` | bool | true for every model in this repo today |

No confidence column. Add one only after an uncertainty method has been implemented and evaluated.

Companion **closures table** (`road_closure_intervals`: `road_segment_id`, `case_num`, `kind`, `restriction`,
`closure_begin`, `closure_end`). Closures keep their exact timestamps and are never smoothed into a congestion
score. Routers must check them at the moment a vehicle enters a road.

Storage suggestion (for discussion): a Tiger hypertable `road_forecast_metrics` partitioned on `valid_from`,
segmented by `road_segment_id`, plus closures in Mongo `road_incidents` (it already has `start_time+end_time` and
`road_segment_ids` indexes). Synthetic-trained forecasts must not be written next to observed `traffic_metrics`.

## Snapshot input the forecaster needs (live path, future work)

* `history`: 6 completed 10-min buckets of `speed_mph`, `observed`, `closed` per road, which is the normalised
  `traffic_metrics` grid described in `AGENTS.md`. A bucket is used only after it has finished.
* `context`: cases (public events with scheduled public hours and an optional *declared* attendance with its source;
  permits) and their scheduled restrictions (segment ids and UTC begin/end). These come from Mongo `events` /
  `road_incidents`.
* `network_version` must match the model's. A snapshot from another network version is refused.

## Fleet-facing adapter (reference implementation: `ml/forecast/adapter.py`)

* Time-dependent FIFO Dijkstra over the network's legal connections (`arcs_c90.json`). A road's cost is the forecast
  for the bucket in which the vehicle enters it.
* A road cannot be entered while a closure interval covers the entry time, when its bucket is `closed` /
  `unavailable`, or when passenger access is barred.
* Entries after the last horizon use the 60-min value and are flagged `beyond_horizon` (explicit fallback).
* Queries: `route(vehicle_road → pickup_road, depart_at)`, `many_to_one(vehicles, pickup, t)`,
  `route(pickup → dropoff, t)`.
* The optimizer's other inputs (requests, fleet positions, capacity, battery, operating constraints) stay separate.
  Passenger demand is not derived from congestion.
