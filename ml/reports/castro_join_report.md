# Join report: Castro Street Fair 2026 (case 1534041)

Generated 2026-09-26T10:42:51+00:00 by `python -m eventsim prepare --event castro`.
Data sources are local `ingest/data` snapshots; rerun to pick up new polling.

## Event (sourced)

- Permit status: {'Permitted': 16}; types: ['Special Event']
- Closure window (UTC, source): 2026-10-04T09:00:00.000Z → 2026-10-05T06:00:00.000Z
- Closure window (SF local): 2026-10-04T02:00:00-07:00 → 2026-10-04T23:00:00-07:00
- Occurrences (case/start/end): 1
- Distinct affected `cnn`: 16
- UTC vs local field disagreements: 0

## Assumptions (not sourced)

- **public_hours_local**: ['2026-10-04T11:00:00-07:00', '2026-10-04T18:00:00-07:00']
- **public_hours_source**: assumption: typical Castro Street Fair hours (not in DataSF records; unverified for 2026)
- **undefined_direction_rows**: closed in both directions
- **partial_restrictions**: lane reduction per scenario config
- **attendance_vehicle_trips**: not in records; varied directly as event vehicle trips in scenarios

## Closure rows → OSM directed edges

Matching uses overlap along the closure line (≤12 m, ≤30° heading difference, ≥50% of the edge), street-name identity, and both travel directions; not a single nearest point.

| cnn | street | from → to | direction | impact | status | edges | closure covered | flags |
|---|---|---|---|---|---|---:|---:|---|
| 3788000 | CASTRO ST | 16TH ST → STATES ST | both | all-lanes-closed | matched | 2 | 100% | — |
| 3789000 | CASTRO ST | STATES ST → 17TH ST | both | all-lanes-closed | matched | 4 | 100% | — |
| 3790000 | CASTRO ST | 17TH ST → 18TH ST | both | all-lanes-closed | matched | 4 | 100% | — |
| 3791000 | CASTRO ST | 18TH ST → 19TH ST | both | all-lanes-closed | matched | 2 | 100% | — |
| 809000 | 17TH ST | NOE ST → HARTFORD ST | both | all-lanes-closed | matched | 2 | 100% | — |
| 810000 | 17TH ST | HARTFORD ST → MARKET ST | both | all-lanes-closed | ambiguous | 2 | 52% | partial_coverage |
| 8766201 | MARKET ST | SANCHEZ ST → NOE ST | undefined | all-lanes-closed | ambiguous | 7 | 100% | name_mismatch, direction_undefined_treated_as_both |
| 8767101 | MARKET ST | NOE ST → CASTRO ST | undefined | all-lanes-closed | ambiguous | 6 | 100% | direction_undefined_treated_as_both |
| 8767201 | MARKET ST | NOE ST → CASTRO ST | undefined | all-lanes-closed | ambiguous | 6 | 100% | direction_undefined_treated_as_both |
| 8768101 | MARKET ST | 17TH ST → COLLINGWOOD ST | undefined | all-lanes-closed | ambiguous | 3 | 100% | direction_undefined_treated_as_both |
| 8768201 | MARKET ST | CASTRO ST → COLLINGWOOD ST | undefined | all-lanes-closed | ambiguous | 3 | 100% | direction_undefined_treated_as_both |
| 8769101 | MARKET ST | COLLINGWOOD ST → DIAMOND ST | undefined | all-lanes-closed | ambiguous | 3 | 100% | name_mismatch, direction_undefined_treated_as_both |
| 890000 | 18TH ST | NOE ST → HARTFORD ST | both | all-lanes-closed | matched | 2 | 100% | — |
| 891000 | 18TH ST | HARTFORD ST → CASTRO ST | both | all-lanes-closed | matched | 2 | 100% | — |
| 892000 | 18TH ST | CASTRO ST → COLLINGWOOD ST | both | all-lanes-closed | matched | 2 | 100% | — |
| 893000 | 18TH ST | COLLINGWOOD ST → DIAMOND ST | both | all-lanes-closed | matched | 2 | 100% | — |

Rows: {'matched': 9, 'ambiguous': 7}. Closed directed edges in patch: 39; closed edges excluded (outside patch SCC): 0 .

Rejected overlaps (street name differs, overlap < 90%, reviewed as parallel/cross streets):

- cnn 8766201: `581047109-581047249-0` Noe Street (100%)
- cnn 8766201: `581047109-6386555583-0` Noe Street (100%)
- cnn 8766201: `581047133-6386555583-0` Noe Street (100%)
- cnn 8766201: `581047249-581047109-0` Noe Street (100%)
- cnn 8766201: `6386555574-6386555583-0` None (100%)
- cnn 8766201: `6386555583-581047133-0` Noe Street (100%)
- cnn 8766201: `6386555583-581047109-0` Noe Street (100%)
- cnn 8767101: `6386555574-6386555583-0` None (100%)
- cnn 8767201: `65296324-260494513-0` Castro Street (100%)
- cnn 8767201: `65345379-581047109-0` 16th Street (100%)
- cnn 8767201: `260494512-6386555574-0` 16th Street (75%)
- cnn 8767201: `260494513-65296324-0` Castro Street (100%)
- cnn 8767201: `581047109-65345379-0` 16th Street (100%)
- cnn 8767201: `581047109-6386555574-0` 16th Street (100%)
- cnn 8767201: `6386555574-260494512-0` 16th Street (75%)
- cnn 8767201: `6386555574-581047109-0` 16th Street (100%)
- cnn 8768201: `703454966-6522764204-0` None (60%)

## Simulation patch

- Radius around the closure footprint: 700 m; largest strongly connected component kept (16 edges dropped as disconnected).
- **Directed segments: 931**; nodes: 355; signalised nodes (OSM tag): 71
- Boundary nodes: 55; entry edges: 92; exit edges: 100
- Approach/exit segments (≤300 m of footprint, open): 355
- Turn prohibitions resolved: 60 pairs; relation stats: {'outside_patch': 1740, 'resolved': 57, 'incomplete': 287, 'via_way_skipped': 438, 'unresolved_in_patch': 3}
- Missing attributes: lanes 534/931 (assumed per road class), DataSF cnn 0/931, posted limit 23/931
- Fallback free-flow source (posted limit is a fallback, not a measurement): {'datasf_posted': 908, 'unposted_default': 21, 'osm_maxspeed': 2}
- Not available: signal timings (SUMO defaults, varied per scenario), capacities, demand (scenario assumptions).

## Other timed restrictions on the event day in the patch bbox

- Special Traffic Permit · Permitted · PG&E · CASELLI AVE between DANVERS ST and YUKON ST · some-lanes-closed · 2026-09-21T08:00:00.000Z → 2026-10-10T07:59:00.000Z · patch edges: 2
- Special Traffic Permit · Permitted · PG&E · CASELLI AVE between CLOVER LN and DANVERS ST · some-lanes-closed · 2026-09-21T08:00:00.000Z → 2026-10-10T07:59:00.000Z · patch edges: 0
- Special Traffic Permit · Permitted · PG&E · CASELLI AVE between CLOVER ST and DANVERS ST · some-lanes-closed · 2026-09-21T08:00:00.000Z → 2026-10-10T07:59:00.000Z · patch edges: 2
- Special Traffic Permit · Permitted · PG&E · CASELLI AVE between CLOVER ST and DANVERS ST · some-lanes-closed · 2026-09-21T08:00:00.000Z → 2026-10-10T07:59:00.000Z · patch edges: 2
- Roadway Shared Spaces · Permitted · Noe St - Artyhood Foundation (2026) · NOE ST between BEAVER ST and MARKET ST · all-lanes-closed · 2026-10-04T18:30:00.000Z → 2026-10-05T04:30:00.000Z · patch edges: 8
- Enforced in simulation (event permit + permitted matches): [('Castro Street Fair 2026', 'full', 39), ('PG&E', 'partial', 2), ('PG&E', 'partial', 2), ('PG&E', 'partial', 2), ('Noe St - Artyhood Foundation (2026)', 'full', 8)]
- 511 events located in bbox (any date): 0

## Real traffic context

- Segments with a TomTom speed line (same direction): 576/931 (62%); approach/exit: 241/355
- Segments with a Mapbox congestion line: 931/931 (100%); matched as undirected line: 371
- TomTom readings joined: absolute 1689, relative 245; lines with an abs/rel free-flow estimate: 53; relative < 0.05 skipped: 0
- Observation buckets: 2026-09-26T09:00:00+00:00 → 2026-09-26T10:30:00+00:00 (10 buckets); overlaps closure window: **False**
- TomTom speed / free-flow: median 0.75, p10 0.37, p90 1.00 (units check; overnight context, not event traffic)
- TomTom median speed 12.4 mph; free-flow sources: {'datasf_posted': 307, 'tomtom_abs_over_rel': 254, 'unposted_default': 8, 'osm_maxspeed': 1}
- Mapbox categories: {'low': 3976, 'moderate': 19, 'heavy': 13, 'severe': 4}

## Status

All closure rows are resolved or listed above; review `ambiguous` rows before trusting closure geometry. Synthetic outputs built from this patch are simulation, not observed traffic.
