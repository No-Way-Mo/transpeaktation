# Join report: Folsom Street Fair 2026 (case 1532891)

Generated 2026-09-26T12:10:21+00:00 by `python -m eventsim prepare --event folsom`.
Data sources are local `ingest/data` snapshots; rerun to pick up new polling.

## Event (sourced)

- Permit status: {'Permitted': 55}; types: ['Special Event']
- Closure window (UTC, source): 2026-09-27T00:00:00.000Z → 2026-09-28T12:00:00.000Z
- Closure window (SF local): 2026-09-26T17:00:00-07:00 → 2026-09-28T05:00:00-07:00
- Occurrences (case/start/end): 1
- Distinct affected `cnn`: 55
- UTC vs local field disagreements: 0

## Assumptions (not sourced)

- **public_hours_local**: ['2026-09-26T11:00:00-07:00', '2026-09-26T18:00:00-07:00']
- **public_hours_source**: assumption: typical Folsom Street Fair hours (not in DataSF records; unverified for 2026)
- **undefined_direction_rows**: closed in both directions
- **partial_restrictions**: lane reduction per scenario config
- **attendance_vehicle_trips**: not in records; varied directly as event vehicle trips in scenarios

## Closure rows → OSM directed edges

Matching uses overlap along the closure line (≤12 m, ≤30° heading difference, ≥50% of the edge), street-name identity, and both travel directions; not a single nearest point.

| cnn | street | from → to | direction | impact | status | edges | closure covered | flags |
|---|---|---|---|---|---|---:|---:|---|
| 10936000 | RAUSCH ST | HOWARD ST → FOLSOM ST | undefined | all-lanes-closed | ambiguous | 1 | 100% | direction_undefined_treated_as_both |
| 11033000 | RINGOLD ST | 08TH ST → 09TH ST | undefined | all-lanes-closed | ambiguous | 1 | 100% | direction_undefined_treated_as_both |
| 11802000 | SHERIDAN ST | 9TH ST → 10TH ST | undefined | all-lanes-closed | ambiguous | 1 | 100% | direction_undefined_treated_as_both |
| 12251000 | SUMNER ST | HOWARD ST → CLEMENTINA ST | both | all-lanes-closed | matched | 2 | 100% | — |
| 12477000 | TEHAMA ST | 08TH ST → 09TH ST | undefined | all-lanes-closed | ambiguous | 1 | 100% | direction_undefined_treated_as_both |
| 2950000 | BERNICE ST | 12TH ST → 13TH ST | both | all-lanes-closed | matched | 2 | 100% | — |
| 2962000 | BERWICK PL | HERON ST → HARRISON ST | undefined | all-lanes-closed | ambiguous | 3 | 100% | direction_undefined_treated_as_both |
| 409000 | 08TH ST | HOWARD ST → TEHAMA ST | undefined | all-lanes-closed | ambiguous | 1 | 100% | direction_undefined_treated_as_both |
| 410000 | 8TH ST | TEHAMA ST → CLEMENTINA ST | undefined | all-lanes-closed | ambiguous | 1 | 100% | direction_undefined_treated_as_both |
| 411000 | 08TH ST | CLEMENTINA ST → FOLSOM ST | undefined | all-lanes-closed | ambiguous | 1 | 100% | direction_undefined_treated_as_both |
| 412000 | 08TH ST | FOLSOM ST → RINGOLD ST | undefined | all-lanes-closed | ambiguous | 1 | 100% | direction_undefined_treated_as_both |
| 413000 | 8TH ST | RINGOLD ST → HERON ST | undefined | all-lanes-closed | ambiguous | 1 | 100% | direction_undefined_treated_as_both |
| 414000 | 8TH ST | HERON ST → HARRISON ST | undefined | all-lanes-closed | ambiguous | 2 | 100% | direction_undefined_treated_as_both |
| 4202000 | CLEMENTINA ST | SUMNER ST → 08TH ST | both | all-lanes-closed | matched | 4 | 100% | — |
| 4203000 | CLEMENTINA ST | 08TH ST → 09TH ST | undefined | all-lanes-closed | ambiguous | 1 | 100% | direction_undefined_treated_as_both |
| 451000 | 9TH ST | HOWARD ST → TEHAMA ST | undefined | all-lanes-closed | ambiguous | 2 | 100% | direction_undefined_treated_as_both |
| 452000 | 9TH ST | TEHAMA ST → CLEMENTINA ST | undefined | all-lanes-closed | ambiguous | 1 | 100% | direction_undefined_treated_as_both |
| 453000 | 9TH ST | CLEMENTINA ST → FOLSOM ST | undefined | all-lanes-closed | ambiguous | 1 | 100% | direction_undefined_treated_as_both |
| 454000 | 09TH ST | FOLSOM ST → RINGOLD ST | undefined | all-lanes-closed | ambiguous | 1 | 100% | direction_undefined_treated_as_both |
| 455000 | 9TH ST | RINGOLD ST → SHERIDAN ST | undefined | all-lanes-closed | ambiguous | 1 | 100% | direction_undefined_treated_as_both |
| 456000 | 09TH ST | SHERIDAN ST → HARRISON ST | undefined | all-lanes-closed | ambiguous | 1 | 100% | direction_undefined_treated_as_both |
| 487000 | 10TH ST | HOWARD ST → FOLSOM ST | undefined | all-lanes-closed | ambiguous | 2 | 100% | direction_undefined_treated_as_both |
| 488000 | 10TH ST | FOLSOM ST → SHERIDAN ST | undefined | all-lanes-closed | ambiguous | 2 | 100% | direction_undefined_treated_as_both |
| 489000 | 10TH ST | SHERIDAN ST → HARRISON ST | undefined | all-lanes-closed | ambiguous | 1 | 100% | direction_undefined_treated_as_both |
| 4929000 | DORE ST | HOWARD ST → FOLSOM ST | undefined | all-lanes-closed | ambiguous | 2 | 100% | direction_undefined_treated_as_both |
| 512000 | 11TH ST | HOWARD ST → KISSLING ST | both | all-lanes-closed | matched | 6 | 100% | — |
| 513000 | 11TH ST | KISSLING ST → BURNS PL | both | all-lanes-closed | matched | 2 | 100% | — |
| 514000 | 11TH ST | BURNS PL → FOLSOM ST | both | all-lanes-closed | matched | 4 | 100% | — |
| 515000 | 11TH ST | FOLSOM ST → HARRISON ST | both | all-lanes-closed | matched | 4 | 100% | — |
| 543000 | 12TH ST | HOWARD ST → KISSLING ST | both | all-lanes-closed | matched | 2 | 100% | — |
| 544000 | 12TH ST | KISSLING ST → FOLSOM ST | both | all-lanes-closed | matched | 2 | 100% | — |
| 545000 | 12TH ST | FOLSOM ST → ISIS ST | both | all-lanes-closed | matched | 2 | 100% | — |
| 546000 | 12TH ST | ISIS ST → BERNICE ST | both | all-lanes-closed | matched | 2 | 100% | — |
| 547000 | 12TH ST | BERNICE ST → HARRISON ST | both | all-lanes-closed | matched | 2 | 100% | — |
| 5673000 | FOLSOM ST | 07TH ST → LANGTON ST | undefined | all-lanes-closed | ambiguous | 2 | 100% | direction_undefined_treated_as_both |
| 5674000 | FOLSOM ST | LANGTON ST → HALLAM ST | undefined | all-lanes-closed | ambiguous | 2 | 100% | direction_undefined_treated_as_both |
| 5675000 | FOLSOM ST | HALLAM ST → RAUSCH ST | undefined | all-lanes-closed | ambiguous | 1 | 100% | direction_undefined_treated_as_both |
| 5676000 | FOLSOM ST | RAUSCH ST → RODGERS ST | undefined | all-lanes-closed | ambiguous | 2 | 100% | direction_undefined_treated_as_both |
| 5677000 | FOLSOM ST | RODGERS ST → 08TH ST | undefined | all-lanes-closed | ambiguous | 1 | 100% | direction_undefined_treated_as_both |
| 5678000 | FOLSOM ST | 8TH ST → TH ST | undefined | all-lanes-closed | ambiguous | 1 | 100% | direction_undefined_treated_as_both |
| 5679000 | FOLSOM ST | 9TH ST → DORE ST | undefined | all-lanes-closed | ambiguous | 1 | 100% | direction_undefined_treated_as_both |
| 5680000 | FOLSOM ST | DORE ST → 10TH ST | undefined | all-lanes-closed | ambiguous | 1 | 100% | direction_undefined_treated_as_both |
| 5681000 | FOLSOM ST | 10TH ST → JUNIPER ST | undefined | all-lanes-closed | ambiguous | 2 | 100% | direction_undefined_treated_as_both |
| 5682000 | FOLSOM ST | JUNIPER ST → 11TH ST | undefined | all-lanes-closed | ambiguous | 2 | 100% | direction_undefined_treated_as_both |
| 5683000 | FOLSOM ST | 11TH ST → NORFOLK ST | both | all-lanes-closed | ambiguous | 5 | 100% | name_mismatch |
| 5684000 | FOLSOM ST | NORFOLK ST → 12TH ST | both | all-lanes-closed | matched | 4 | 100% | — |
| 5685000 | FOLSOM ST | 12TH ST → 13TH ST | both | all-lanes-closed | matched | 4 | 100% | — |
| 6629000 | HALLAM ST | FOLSOM ST → BRUSH PL | both | all-lanes-closed | matched | 4 | 100% | — |
| 6893000 | HERON ST | BERWICK PL → 08TH ST | both | all-lanes-closed | matched | 1 | 100% | — |
| 7330000 | ISIS ST | 12TH ST → 13TH ST | both | all-lanes-closed | matched | 2 | 100% | — |
| 7903000 | KISSLING ST | 11TH ST → 12TH ST | both | all-lanes-closed | matched | 2 | 100% | — |
| 8098000 | LANGTON ST | HOWARD ST → FOLSOM ST | both | all-lanes-closed | matched | 1 | 100% | — |
| 8099000 | LANGTON ST | FOLSOM ST → DECKER ALY | undefined | all-lanes-closed | unmatched | 0 | 0% | — |
| 8100000 | LANGTON ST | DECKER ALY → HARRISON ST | undefined | all-lanes-closed | ambiguous | 1 | 100% | direction_undefined_treated_as_both |
| 9642000 | NORFOLK ST | FOLSOM ST → HARRISON ST | undefined | all-lanes-closed | ambiguous | 1 | 82% | direction_undefined_treated_as_both |

Rows: {'ambiguous': 35, 'matched': 19, 'unmatched': 1}. Closed directed edges in patch: 94; closed edges excluded (outside patch SCC): 1 ['7133541709-65317574-0'].

Rejected overlaps (street name differs, overlap < 90%, reviewed as parallel/cross streets):

- cnn 5681000: `9684849383-9684849385-0` None (77%)

## Simulation patch

- Radius around the closure footprint: 700 m; largest strongly connected component kept (34 edges dropped as disconnected).
- **Directed segments: 1075**; nodes: 502; signalised nodes (OSM tag): 142
- Boundary nodes: 74; entry edges: 112; exit edges: 109
- Approach/exit segments (≤300 m of footprint, open): 403
- Turn prohibitions resolved: 144 pairs; relation stats: {'resolved': 131, 'outside_patch': 1652, 'incomplete': 287, 'via_way_skipped': 438, 'unresolved_in_patch': 17}
- Missing attributes: lanes 318/1075 (assumed per road class), DataSF cnn 0/1075, posted limit 51/1075
- Fallback free-flow source (posted limit is a fallback, not a measurement): {'datasf_posted': 1024, 'osm_maxspeed': 32, 'unposted_default': 19}
- Not available: signal timings (SUMO defaults, varied per scenario), capacities, demand (scenario assumptions).

## Other timed restrictions on the event day in the patch bbox

- Special Traffic Permit · Permitted · NIBBI BROS · 16TH ST between 08TH ST and HUBBELL ST · some-lanes-closed · 2026-09-22T08:00:00.000Z → 2026-10-20T07:59:00.000Z · patch edges: 0
- Special Traffic Permit · Permitted · NIBBI BROS · 16TH ST between 08TH ST and HUBBELL ST · some-lanes-closed · 2026-09-22T08:00:00.000Z → 2026-10-20T07:59:00.000Z · patch edges: 0
- Special Traffic Permit · Permitted · LEND LEASE · FELL ST between MARKET ST and VAN NESS AVE · some-lanes-closed · 2026-07-02T08:00:00.000Z → 2026-10-02T07:59:00.000Z · patch edges: 5
- Special Traffic Permit · Permitted · LEND LEASE · VAN NESS AVE between FELL ST and MARKET ST · some-lanes-closed · 2026-07-02T08:00:00.000Z → 2026-10-02T07:59:00.000Z · patch edges: 1
- Special Traffic Permit · Permitted · LEND LEASE · VAN NESS AVE between FELL ST and MARKET ST · some-lanes-closed · 2026-07-02T08:00:00.000Z → 2026-10-02T07:59:00.000Z · patch edges: 1
- Special Traffic Permit · Permitted · LEND LEASE · VAN NESS AVE between FELL ST and MARKET ST · some-lanes-closed · 2026-07-02T08:00:00.000Z → 2026-10-02T07:59:00.000Z · patch edges: 0
- Special Traffic Permit · Permitted · THOMPSON BUILDERS · 16TH ST between DE HARO ST and RHODE ISLAND ST · some-lanes-closed · 2026-08-27T08:00:00.000Z → 2026-09-27T07:59:00.000Z · patch edges: 0
- Special Traffic Permit · Permitted · LP CONSTRUCTION · FELL ST between FRANKLIN ST and VAN NESS AVE · some-lanes-closed · 2026-09-17T08:00:00.000Z → 2026-12-17T07:59:00.000Z · patch edges: 5
- Special Traffic Permit · Permitted · ANOTHER PLANET ENT · LARKIN ST between GROVE ST and HAYES ST · some-lanes-closed · 2026-09-08T08:00:00.000Z → 2026-10-30T07:59:00.000Z · patch edges: 2
- Special Traffic Permit · Permitted · HATTONS CRANE · OAK GROVE ST between BRYANT ST and HARRISON ST · some-lanes-closed · 2026-09-26T08:00:00.000Z → 2026-09-27T07:59:00.000Z · patch edges: 2
- Special Traffic Permit · Permitted · ANOTHER PLANET ENT · HAYES ST between LARKIN ST and POLK ST · some-lanes-closed · 2026-09-04T08:00:00.000Z → 2026-10-05T07:59:00.000Z · patch edges: 2
- Special Traffic Permit · Permitted · PHOENIX ELECTRIC · 17TH ST between BRYANT ST and HAMPSHIRE ST · some-lanes-closed · 2026-09-21T08:00:00.000Z → 2026-10-17T07:59:00.000Z · patch edges: 0
- Special Traffic Permit · Permitted · PHOENIX ELECTRIC · MARIPOSA ST between BRYANT ST and HAMPSHIRE ST · some-lanes-closed · 2026-09-21T08:00:00.000Z → 2026-10-17T07:59:00.000Z · patch edges: 0
- Special Traffic Permit · Permitted · PHOENIX ELECTRIC · MARIPOSA ST between BRYANT ST and HAMPSHIRE ST · some-lanes-closed · 2026-09-21T08:00:00.000Z → 2026-10-17T07:59:00.000Z · patch edges: 0
- Special Traffic Permit · Permitted · PHOENIX ELECTRIC · HAMPSHIRE ST between 17TH ST and MARIPOSA ST · some-lanes-closed · 2026-09-21T08:00:00.000Z → 2026-10-17T07:59:00.000Z · patch edges: 0
- Roadway Shared Spaces · Permitted · Hayes St. - HVNA (2025-26) · HAYES ST between OCTAVIA ST and GOUGH ST · all-lanes-closed · 2026-09-26T17:00:00.000Z → 2026-09-27T05:00:00.000Z · patch edges: 0
- Roadway Shared Spaces · Permitted · Dodge St - TLCBD 2025-26 · DODGE ST between TURK ST and START: 1-99 BLOCK · all-lanes-closed · 2026-09-26T22:00:00.000Z → 2026-09-27T05:00:00.000Z · patch edges: 0
- Roadway Shared Spaces · Permitted · Golden Gate Ave - Shared Space 2026 · GOLDEN GATE AVE between LEAVENWORTH ST and JONES ST · all-lanes-closed · 2026-09-26T13:00:00.000Z → 2026-09-27T01:00:00.000Z · patch edges: 1
- Special Event · Permitted · Mr. S Geared Up Street Party · HERON ST between 8TH ST and BERWICK PL · all-lanes-closed · 2026-09-25T12:00:00.000Z → 2026-09-27T04:00:00.000Z · patch edges: 1
- Special Event · Permitted · Hayes Valley Farmers Market · HAYES ST between OCTAVIA ST and GOUGH ST · all-lanes-closed · 2026-09-26T14:00:00.000Z → 2026-09-26T22:00:00.000Z · patch edges: 0
- Special Event · Permitted · AMZN Unboxed 2026 (SF) · HOWARD ST between 4TH ST and 5TH ST · some-lanes-closed · 2026-09-23T13:00:00.000Z → 2026-10-03T01:00:00.000Z · patch edges: 0
- Enforced in simulation (event permit + permitted matches): [('Folsom Street Fair 2026', 'full', 94), ('LEND LEASE', 'partial', 5), ('LEND LEASE', 'partial', 1), ('LEND LEASE', 'partial', 1), ('LP CONSTRUCTION', 'partial', 5), ('ANOTHER PLANET ENT', 'partial', 2), ('HATTONS CRANE', 'partial', 2), ('ANOTHER PLANET ENT', 'partial', 2), ('Golden Gate Ave - Shared Space 2026', 'full', 1), ('Mr. S Geared Up Street Party', 'full', 1)]
- 511 events located in bbox (any date): 1

## Real traffic context

- Segments with a TomTom speed line (same direction): 830/1075 (77%); approach/exit: 302/403
- Segments with a Mapbox congestion line: 1075/1075 (100%); matched as undirected line: 290
- TomTom readings joined: absolute 3997, relative 336; lines with an abs/rel free-flow estimate: 89; relative < 0.05 skipped: 0
- Observation buckets: 2026-09-26T09:00:00+00:00 → 2026-09-26T12:00:00+00:00 (19 buckets); overlaps closure window: **False**
- TomTom speed / free-flow: median 0.62, p10 0.37, p90 1.00 (units check; overnight context, not event traffic)
- TomTom median speed 12.4 mph; free-flow sources: {'datasf_posted': 514, 'tomtom_abs_over_rel': 277, 'osm_maxspeed': 10, 'unposted_default': 8}
- Mapbox categories: {'low': 7806, 'heavy': 56, 'moderate': 45, 'severe': 3}

## Status

All closure rows are resolved or listed above; review `ambiguous` rows before trusting closure geometry. Synthetic outputs built from this patch are simulation, not observed traffic.
