# Citywide simulation data pilot

This batch generates data only. No model has been trained.

- Canonical SF graph: 27,632 directed segments.
- SUMO network: 26,730 explicit road edges; 875 junction connectors absorbed; 27 self-loop roads omitted by conversion; 0 unexplained omissions.
- Real special-event permit cases indexed for matching: 184 (recurrences and multiple road rows retained; unresolved matches remain explicit).
- Event closure-row matching: {'ambiguous': 216, 'matched': 741, 'unmatched': 148}.
- Roads carrying traffic in at least one completed run: 98.65% of directed length; 98.45% of physical street length.
- Physical coverage counts coincident reverse geometries once; it is based on the local OSM graph, not an external administrative-road inventory.
- Missing or unused roads stay unobserved. They are not filled with invented speeds.

| Run | Trips | Unfinished (includes uninstered trips) | Not inserted/no route | Teleports | Physical length covered | Closed-edge entries | Runtime s |
|---|---:|---:|---:|---:|---:|---:|---:|
| castro_arrival_v1_control | 23795 | 0 | 0 | 66 | 98.35% | 0.0 | 334.3 |
| castro_arrival_v1_event | 24871 | 0 | 0 | 126 | 98.16% | 0.0 | 379.2 |
| folsom_arrival_v1_control | 24131 | 0 | 0 | 137 | 98.16% | 0.0 | 361.5 |
| folsom_arrival_v1_event | 26346 | 0 | 0 | 112 | 98.02% | 0.0 | 362.7 |

## What is sourced and what is assumed

Road topology, named event footprints, permit restrictions, street IDs and available speed limits come from real snapshots. Public schedules for Castro and Folsom are separately sourced in citywide.py. The simulator uses assumed OD demand, 90-second signal cycles, missing lane defaults, and event vehicle demand. It is not a measured or calibrated reconstruction of either event.

Event runs use only the selected event's matched full-closure rows. Ambiguous direction rows are explicitly treated as both directions; unresolved rows and other concurrent restrictions are not yet enforced. Those cases remain in prepared/closure_matches.json for review. This pilot must not be treated as training-approved merely because the processes finish.

## Artifacts

Under ml/data/sf_citywide/: prepared/patch.json, event_catalog.json, closure_matches.json, source_mapping.json, source_manifest.json; net/crosswalk.csv and net_c90.net.xml; scenarios.json; runs/<run>/measurements.npz, trips.csv, summary.json and raw SUMO outputs; coverage.json.

Raw measurements use canonical road IDs and 10-minute buckets with SUMO speed in m/s. The export stage produces mph, 10-minute UTC timestamps, congestion ratios, run IDs and synthetic provenance in export/*.csv.gz. Empty-road values remain missing. Model-ready windowing, large-batch generation, full-day demand diversity, replay presentation, and real-event validation are subsequent stages.
