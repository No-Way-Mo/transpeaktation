# Congestion map (ml writes, routing reads)

One map per forecaster model × 10-min issue time, written on demand by `ml/forecast/live.py` (forecast service
`POST /v1/live/forecast`) and read by `ml/coordination/live.py`. Built from Tiger `traffic_metrics` + Mongo
`road_incidents` closures / `events`. The forecaster is trained on synthetic SUMO traffic; nothing here is validated
on real traffic.

## Tiger `prediction_metrics` (one row per road × 10-min interval)

| Column | Meaning |
|---|---|
| `issued_at` | issue time = end of the newest complete `traffic_metrics` bucket (≤ now; ingest lags ~10-25 min) |
| `time`, `valid_to` | interval `[issued_at + 10(k-1) min, issued_at + 10k min)` |
| `prediction_horizon_min` | `10k`, k = 1..6 for the current model |
| `road_segment_id` | OSM `u-v-key` (= Mongo `road_segments.segment_id`); every canonical road, 27,632 rows per interval |
| `predicted_travel_time_sec`, `predicted_speed_mph`, `predicted_congestion_ratio` | NULL when the road cannot be entered in the interval |
| `predicted_delay_sec` | travel time − free-flow travel time |
| `current_speed_mph` | fused observed speed in the last history bucket (NULL = unobserved) |
| `availability` | `open` / `closed` (full closure covers the interval) / `restricted` (partial cover, see closures) / `unavailable` (not modelled / no car access) |
| `restriction_reason`, `prediction_source` (`model` / `representative_road` / `none`), `represented_by` | as in `ml/forecast/CONTRACT_PROPOSAL.md` |
| `model_version`, `network_version`, `input_source` (`live_tiger_mongo`) | identity |
| `confidence` | always NULL: no uncertainty method exists |

## Mongo `forecast_runs` (one doc per map; the map exists only once this doc has `status: "ready"`)

`_id = "<model_version>|<issued_at ISO>"`, `issued_at`, `model_version`, `network_version`, `checkpoint_sha256`,
`dataset_id`, `training_source`, `synthetic_training`, `horizons`, `bucket_min`, `rows`, `created_at`,
`closures: [{road_segment_id, case_num, kind, restriction (full|lane), closure_begin, closure_end}]` (the exact
intervals the map used; routing blocks entry during `full`), `coverage` (observed share per history bucket, traffic
rows per source, cases), `seconds`, `note`. The rows are written in one transaction before this doc.
