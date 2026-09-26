# Ingestion worker design

Layer 2 of `ARCHITECTURE.md`. Takes every source in `TODO.md` plus PredictHQ and Google Routes, normalizes it into one vocabulary, and writes long-lived entities to **MongoDB** and numbers-over-time to **Tiger Data**.

This builds on what already runs (`pull/`, `datasf/`) and on the reference worker in `~/Downloads/transpeaktation-ingest`. §11 lists where it deliberately differs from that reference.

**Status:** steps 1–3 are built in `worker/` (road segments, traffic loaders, closures/incidents except 511; see `TODO.md`); events, Google and SUMO are proposal. Neither database is set up yet. The collections in `AGENTS.md` and the tables in `contracts/tiger_schema.sql` are drafts. §4–§6 propose the schema from what each source actually returns (§3b). Once the team agrees, it replaces those drafts in one `contracts/` PR. Traffic rows follow the rules already in `AGENTS.md` → "Traffic data normalization": 10-min buckets, `speed_mph` / `free_flow_speed_mph` / `congestion_ratio`, sources `tomtom`, `mapbox_route`, `mapbox_tiles`, `muni`.

## 1. Pipeline shape

Every job runs the same five steps:

```
fetch            reuse pull/ fetchers (stdlib HTTP, retries, 511 BOM, CHP partial XML)
  -> archive     raw payload to disk: data/raw/<source>/<UTC date>.jsonl.gz
  -> normalize   source record -> our shape (UTC times, GeoJSON [lon, lat], mph, our enums)
  -> link        snap to road_segments (segment_id), attach venue_id / event_id
  -> upsert      Mongo: deterministic _id + content_hash (skip unchanged)
                 Tiger: INSERT ... ON CONFLICT DO NOTHING on a unique index
  -> log         per-source watermark in data/worker/state.json (next to the data it tracks);
                 Mongo ingest_runs (counts, errors, duration) once the transparency page needs it
```

Live traffic is already fetched by `python -m pull.poll`, which appends JSONL to `data/timeseries/<feed>/`. Those files are the archive, so the traffic jobs read them rather than calling the APIs a second time. Every other source is fetched by the worker and archived the same way.

Raw payloads go to disk, not Mongo. The cluster is an M0 with 512 MB, and one Mapbox leg with full annotations is tens of KB: 17 legs every 10 minutes adds more than 100 MB a day. The disk archive also lets us replay: `python -m worker replay <source> --date D` re-runs normalize, link and upsert with no API calls.

## 2. Shared keys (the only things other folders join on)

| Key | Format | Defined by | Used in |
|---|---|---|---|
| `segment_id` | `u-v-key` (OSMnx edge, direction-aware) | `osm_segments` job | Mongo `road_segments`, `road_incidents.road_segment_ids`, `route_plans.segment_ids`; Tiger `road_segment_id` everywhere |
| `cnn` | DataSF street ID (string) | DataSF `streets` | `road_segments.cnn`; lets cnn-only data (permits, speed limits) reach a `segment_id` |
| `event_id` | `evt_<sha1[:16]>` | `events` store | Mongo `events._id`, `road_incidents.event_id`; Tiger `demand_metrics` / `prediction_metrics.event_id` |
| `venue_id` | `seed:<slug>` or `phq:<entity_id>` | seeds / PredictHQ | `events.venue_id` |
| `corridor_id` + `direction` | key from `pull/corridors.py`, `ab`/`ba` | code | Mongo `corridors`, `route_plans`; Tiger `route_eta_metrics` |
| `route_plan_id` | `<provider>:<sha1 of rounded geometry>[:20]` | probes | Mongo `route_plans._id`; Tiger `route_eta_metrics` |

## 3. Sources → jobs → stores

| Source | Job | Cadence | Mongo | Tiger |
|---|---|---|---|---|
| OSMnx drive graph | `osm_segments` | bootstrap, weekly | `road_segments` (+ saves `data/sf_drive.graphml` for the matcher) | — |
| DataSF `streets`, `speed_limits`, `tow_away_zones` | `datasf_rules` | nightly, after `osm_segments` | `road_segments.cnn`, `speed_limit_mph`, `tow_away` windows | — |
| TomTom flow tiles (`timeseries/tomtom_flow`) | `traffic_tomtom` | every 10 min, reads new JSONL lines | — | `traffic_metrics` (`source=tomtom`) |
| Mapbox Directions corridors (`timeseries/mapbox_corridors`) | `traffic_mapbox_route` | every 10 min | `route_plans` (probe geometry + segment list) | `traffic_metrics` (`source=mapbox_route`), `route_eta_metrics` |
| Mapbox traffic tiles (`timeseries/mapbox_traffic`) | `traffic_mapbox_tiles` | every 20 min | — | `traffic_metrics` (`source=mapbox_tiles`, ratio only) |
| Muni vehicles (`timeseries/muni_vehicles`) | `traffic_muni` | every 10 min | — | `traffic_metrics` (`source=muni`) |
| Google Routes `computeRoutes` | `google` | hot corridors only, 15 min, plus 1 future-departure forecast | `route_plans` | `route_eta_metrics` (`departure_time > time` = forecast) |
| DataSF `street_closures` | `incidents_datasf` | 15 min | `road_incidents`; special-event rows also merged into `events` | — |
| DataSF `street_use_permits`, `excavation_permits` | `incidents_datasf` | 60 min | `road_incidents` (`kind=permit`) | — |
| DataSF `police_dispatch` (traffic call types only) | `incidents_live` | 5 min | `road_incidents` (`kind=dispatch`) | — |
| Caltrans D4 lane closures | `incidents_state` | 15 min | `road_incidents` (clipped to SF bbox) | — |
| CHP incidents | `incidents_live` | 5 min | `road_incidents` | — |
| 511 `/traffic/events` (`timeseries/sf511_events`, written by `pull.poll` when new or updated) | `incidents_511` | every 10 min | `road_incidents`; `SPECIAL_EVENT` also merged into `events` | — |
| 511 `/traffic/wzdx` | `incidents_511` | 30 min, full snapshot (anything unseen → `status=removed`) | `road_incidents` | — |
| PredictHQ `/v1/events` | `predicthq` | 30 min incremental (`updated.gte`, `state=active,deleted,predicted`), nightly full | `events`, `venues` | — |
| PredictHQ `/v1/features` | `predicthq_features` | nightly (phase 4, only if our plan includes it) | — | `phq_daily_features` (proposed, §6) |
| SUMO `edgeData` XML | `sumo` (manual, per run) | per simulation | — | `simulation_metrics` |
| Seeds: venues + capacity | `bootstrap` | on change | `venues`, `corridors` | — |

Not ingested for now:
- **Parking regulations, street sweeping, parking signs.** These are curb rules for pickup and drop-off, not traffic. They become a curb layer later.
- **Clearance heights.** Only needed if we route tall vehicles.

## 3b. What the data gives us (drives the schema)

| Source | What we actually get | Consequence for storage |
|---|---|---|
| TomTom flow tiles | Speed (km/h) + closure flag on every road line TomTom covers: ~59% of SF road length, nearly all arterials, ~36% of residential. Relative tiles every 6 h give the fraction of free flow. | The main **speed** source, and the only one with a measured **free flow** (absolute ÷ relative). Tile lines re-split between polls, so they must be snapped to OSM segments. |
| Mapbox Directions | Per coordinate pair on our 17 corridor legs: `speed` (m/s), `congestion_numeric` 0–100, `distance`, `duration`, `maxspeed`. Per route: `duration`, `duration_typical`, geometry. No road IDs. | Exact speed on few roads (3% of road length). The route-level ETA and `duration_typical` feed `route_eta_metrics`. `duration_typical` is usual traffic, **not** free flow. |
| Mapbox traffic tiles | Congestion level low/moderate/heavy/severe on ~100% of road lines, including residential. No speed. | Fills the coverage gap as a **ratio only** (calibrated per road class against segments that also have a measured speed), with `speed_mph` null. |
| Muni vehicles | GPS fix per in-service vehicle every 90 s. | Speed between consecutive fixes. It runs low because buses stop, so it stays its own `source` and is never averaged into the others. |
| Google Routes | Per route: `duration`, `staticDuration`, `distanceMeters`, polyline, `speedReadingIntervals` (NORMAL/SLOW/TRAFFIC_JAM over polyline index ranges). Accepts a future `departureTime`. | **No speed**, only a 3-level congestion band, and TomTom plus Mapbox tiles already cover congestion, so Google doesn't write segment rows. Its unique value is **forecast ETAs** → a route-level table keyed by departure time. |
| OSMnx | Directed edges `u-v-key` with geometry, `highway`, `lanes`, `oneway`, `maxspeed` (~26% of edges), `length`. | Becomes the segment vocabulary every other source snaps to. Changes weekly at most → Mongo document. Its posted/`maxspeed` speed is the free-flow fallback where TomTom has no reading. |
| DataSF streets / speed limits | `cnn` per street segment or intersection; posted limit on ~23% (`0` = unposted, `99` = freeway). | `cnn` is a second road key. Link it to `segment_id` once, nightly. The speed limit feeds free flow. |
| DataSF closures / permits, Caltrans, CHP, 511, WZDx | Every source has its own shape: lines, points, cnn-only, recurring schedules, nested lane lists, local vs UTC times. | Nested, irregular, long-lived → **Mongo** `road_incidents`, normalized to a common core (`kind`, `is_closure`, `start_time/end_time`, `windows`, `road_segment_ids`). Status changes are updates, not a time series. |
| PredictHQ Events | Title, category, start/end (plus `predicted_end`), point or area, venue entity, `phq_attendance`, `rank`, `local_rank`, `impact_patterns`, state (active/deleted + reason). **No venue capacity.** | **Mongo** `events` + `venues`. Capacity comes from our seed file. |
| Ticketmaster (fallback) | Title, classification, start, venue with lat/lon. **No attendance, no end time.** | Same `events` doc with `attendance: null`. The impact model then relies on seeded `capacity` and a default duration per category. |
| PredictHQ Features | Daily per-location aggregates (attendance stats, spend, holiday ranks). | Numbers over time → a Tiger table, only if our plan includes the Features API. |
| SUMO `edgeData` | Per edge × interval: `speed`, `density`, `occupancy`, `waitingTime`, `traveltime`, `entered`/`left`. Edge ids carry the OSM way id. | Tiger `simulation_metrics`, mapped back to `segment_id`. |
| Fleet, demand, predictions | **No external source.** AV positions come from our own simulator, demand from trip requests plus events, predictions from `ml/`. | Keep those Tiger tables as drafts owned by `api/` and `ml/`. Ingest doesn't write them. |

## 4. MongoDB documents

All times are UTC `Date`s and all geometry is GeoJSON `[lon, lat]`. Every ingest-written doc carries `source`, `first_seen_at`, `last_seen_at`, `content_hash`, `updated_at`. The field names in `AGENTS.md` are kept exactly.

**`road_segments`**: one per OSM edge (as built).
```js
{ segment_id: "65290756-65303491-0", u, v, key, osmid, name, highway, oneway, lanes, length_m,
  maxspeed_mph,          // OSM tag (~26% of edges)
  speed_limit_mph,       // DataSF posted limit via cnn (0 = unposted and 99 = freeway are not limits)
  free_flow_speed_mph,   // speed_limit_mph ?? maxspeed_mph ?? road-class default (25 mph unposted)
  cnn,                   // nearest DataSF street to the edge midpoint (99% of edges)
  geometry: LineString, first_seen_at, last_ingested_at }
// indexes (AGENTS.md): segment_id unique, cnn, geometry 2dsphere
```

**`road_incidents`**: closures, permits, crashes, dispatch (as built; closure code ported from `ingestion-workers-v1`). Upsert key `source` + `source_id`.
```js
{ source: "street_closures" | "street_use_permits" | "excavation_permits" | "caltrans_lane_closures"
        | "chp_incidents" | "police_dispatch",        // 511 + WZDx next
  source_id,                     // natural key; Caltrans = row index (one per closure window)
  incident_type: "closure" | "incident",
  category,                      // street_closure | street_use_permit | excavation | lane_closure | collision | hazard | closure
  is_closure: true,              // closed to traffic -> hard routing constraint
  location: GeoJSON,             // source shape (Point / LineString / MultiLineString); 2dsphere
  location_status: "exact" | "from_cnn" | "geocoded" | "withheld" | "unlocated",
  start_time, end_time, reported_at,
  road_segment_ids: [..], cnn, cnn_match,
  details: {...},                // normalized per-source attributes (lanes, route, call type, ...)
  source_fields: {...},          // raw row minus geometry
  provenance: {source, source_id, pulled_at, also_reported_by: [..]},
  schema_version, first_seen_at, last_ingested_at }
// indexes: source+source_id unique, location 2dsphere, start_time+end_time, road_segment_ids, is_closure+end_time
```
Rules: police keeps traffic calls only (collision, hazard, closure); sensitive calls stay `withheld` and are never geocoded; parking signs aren't stored; bad rows go to `data/quarantine/<source>.jsonl`; a report seen by two sources is stored once, on the higher-priority source, with the other in `provenance.also_reported_by`.

**`events`**: one canonical doc per real-world event, merged across sources, `_id = event_id`.
```js
{ title, category: "concert" | "sports" | "festival" | "conference" | "parade" | "holiday"
                 | "community" | "other",
  start_time, end_time, end_is_predicted, all_day,
  location: Point, venue_id, capacity, attendance, rank, local_rank,
  status: "active" | "cancelled" | "postponed" | "archived",
  road_closure_ids: [..],        // road_incidents._id
  source_names: ["predicthq", "sf511"],
  sources: { predicthq: {id, updated, hash, data}, sf511: {...}, datasf: {...} } }
// indexes: location 2dsphere, start_time+status, end_time, sources.<name>.id unique (partial)
```

**`venues`**: `_id = "seed:<slug>"` (from `worker/seeds/venues.json`) or `"phq:<entity_id>"`. Fields: `name`, `aliases`, `location`, `capacity`, `capacity_note: "approximate, verify"`, `phq_entity_ids[]`. PredictHQ doesn't publish capacity, so capacity only comes from the seed file.

**`route_plans`** (shared with `api/`): probe routes carry `kind: "probe"`. `api/` writes `kind: "candidate" | "chosen"` for real trips.
```js
{ _id: route_plan_id, kind: "probe", provider, corridor_id, direction,
  geometry: LineString, segment_ids: [..ordered], last_summary: {duration_sec, typical_duration_sec, distance_m} }
```

**New, ingest-owned** (add to `AGENTS.md` when they land):
- `corridors`: mirror of `pull/corridors.py` plus `watch_venue_ids` and `hot_radius_m`, so `web/` can draw them.
- `ingest_runs`: one doc per run, TTL 30 days. It also feeds the AI transparency page (what was ingested, when, from where).
- `ingest_state`: per-source watermark.

## 5. Which store gets what

The rule: a number sampled over and over goes to **Tiger**. A thing with identity, shape and changing status goes to **Mongo**.

| Data | Store | Why |
|---|---|---|
| Road segments, cnn link, speed limits | Mongo `road_segments` | Geometry and 2dsphere queries ("segments near this venue") are Mongo's. Tiger rows already carry `free_flow_speed_mph`, so no SQL mirror is needed. |
| Segment speed and congestion (TomTom, Mapbox, Muni) | Tiger `traffic_metrics` | One row per segment × 10-min bucket × source, roughly 20–30k per bucket city-wide. Queried by segment + time range. |
| Route ETAs, live and forecast | Tiger `route_eta_metrics` | Numbers over time. The demo's "predicted vs actual" is a SQL join on this table. |
| Probe route geometry + ordered segment list | Mongo `route_plans` | Rarely changes (same few routes per corridor). Stored once, referenced by `route_plan_id`. |
| Closures, permits, crashes, work zones | Mongo `road_incidents` | Irregular nested shapes. Status changes are updates. Routing asks "closed at time T?" using `start_time`, `end_time`, `windows`. |
| Events, venues | Mongo `events`, `venues` | Multi-source merge, nested per-source blocks. |
| PredictHQ daily features | Tiger `phq_daily_features` | Daily numbers with a forecast vintage (`as_of`). |
| SUMO output | Tiger `simulation_metrics` | Per edge × interval numbers, before/after comparison in SQL. |
| Raw API payloads | Disk (gzip JSONL) | Too big for M0, only needed for replay and debugging. |

Left out on purpose: time series of incident or event changes (the reference's `incident_obs` / `event_obs`). Mongo keeps each incident with its windows and final status, which is enough to reconstruct "what was closed when". Attendance drift is not worth a table yet.

## 6. Tiger Data schema (proposed; replaces the ingest-fed parts of `contracts/tiger_schema.sql`)

Units are **mph, seconds, metres**. The mph matches the drafts and a US demo; converting happens once, at ingest.

```sql
-- traffic_metrics: columns as drafted in contracts/tiger_schema.sql, filled per AGENTS.md "Traffic data normalization".
-- Only addition: idempotent writes, so reloading a JSONL file never double counts a bucket.
CREATE UNIQUE INDEX IF NOT EXISTS traffic_metrics_uq ON traffic_metrics (road_segment_id, source, time);

-- Route-level ETAs, live and forecast. The demo's "normal routing said 27 min, reality was 44":
-- a Google forecast row (departure_time in the future) compared to the live rows observed at that time.
CREATE TABLE IF NOT EXISTS route_eta_metrics (
    time TIMESTAMPTZ NOT NULL,              -- when we asked
    corridor_id TEXT NOT NULL,
    direction TEXT NOT NULL,                -- ab | ba
    provider TEXT NOT NULL,                 -- mapbox | google
    route_idx SMALLINT NOT NULL,            -- 0 = provider's pick, 1+ = alternatives
    departure_time TIMESTAMPTZ NOT NULL,    -- = time for live; later for forecasts
    duration_sec DOUBLE PRECISION,
    typical_duration_sec DOUBLE PRECISION,  -- Mapbox duration_typical (usual traffic)
    static_duration_sec DOUBLE PRECISION,   -- Google staticDuration (no traffic)
    distance_m DOUBLE PRECISION,
    route_plan_id TEXT,                     -- Mongo route_plans._id
    event_id TEXT                           -- hot event that triggered the probe, if any
) WITH (tsdb.hypertable, tsdb.partition_column='time', tsdb.segmentby='corridor_id');
CREATE UNIQUE INDEX IF NOT EXISTS route_eta_metrics_uq
    ON route_eta_metrics (corridor_id, direction, provider, route_idx, departure_time, time);

-- SUMO edgeData, mapped to segment_id (unmatched edges kept as 'sumo:<edge_id>').
CREATE TABLE IF NOT EXISTS simulation_metrics (
    time TIMESTAMPTZ NOT NULL,              -- run start + interval begin
    run_id TEXT NOT NULL,
    scenario TEXT NOT NULL,                 -- baseline | transpeaktation
    road_segment_id TEXT NOT NULL,
    vehicle_count INTEGER,                  -- entered
    avg_speed_mph DOUBLE PRECISION,
    avg_delay_sec DOUBLE PRECISION,         -- traveltime - length / free_flow
    waiting_time_sec DOUBLE PRECISION,
    density_veh_per_km DOUBLE PRECISION,
    throughput_vph DOUBLE PRECISION         -- left / interval hours
) WITH (tsdb.hypertable, tsdb.partition_column='time', tsdb.segmentby='run_id');
CREATE UNIQUE INDEX IF NOT EXISTS simulation_metrics_uq ON simulation_metrics (run_id, scenario, road_segment_id, time);
```

How each source fills `traffic_metrics` (`time` = 10-min UTC bucket start, readings averaged within the bucket):

| Source | `speed_mph` | `free_flow_speed_mph` | `congestion_ratio` | `travel_time_sec` |
|---|---|---|---|---|
| `tomtom` | absolute km/h → mph | absolute ÷ relative (latest relative tile, ≤ 6 h old) | `1 − speed/free_flow`, clamped to [0, 1] | `length_m / speed` |
| `mapbox_route` | distance-weighted mean of piece speeds (m/s → mph) | TomTom on the same segment, else posted limit / OSM `maxspeed`, else 25 | same | same |
| `mapbox_tiles` | null | same fallback as `mapbox_route` | low/moderate/heavy/severe → calibrated per road class (until calibrated 0.1 / 0.4 / 0.65 / 0.85) | null |
| `muni` | speed between consecutive fixes of one in-service vehicle | same fallback | same | null |

Only observed buckets are stored; gap filling happens in `ml/`. A 20-min Mapbox tile poll lands in every other bucket.

Also:
- `phq_daily_features (day, as_of, location_key, feature, …)` comes later, and only if the PredictHQ plan includes the Features API. Its `as_of` column keeps training leakage-safe.
- `av_positions`, `demand_metrics`, `prediction_metrics` stay as drafts for `api/` and `ml/` to finalize. No ingested source feeds them.

## 7. Linking to road segments

- **Lines (TomTom and Mapbox tile lines, Mapbox and Google routes, 511, WZDx, DataSF closures).** Load `data/sf_drive.graphml` once and project it. For each consecutive coordinate pair, snap the midpoint to the nearest edge (≤ 30 m). If the piece runs against the edge, flip to the reverse edge `v-u`: inbound and outbound traffic differ, and around an event that difference is the whole point. The result is an ordered, de-duplicated `segment_ids` list.
- **Points (CHP, dispatch, Caltrans without a shape).** Nearest edge within 50 m, both directions.
- **Muni fixes.** Snap the pair of consecutive fixes like a line piece, so the speed lands on the direction the bus travelled.
- **cnn-only data (excavation permits, speed limits).** Look up `road_segments.cnn`. The `cnn` link itself is built nightly: each DataSF street line is snapped to the OSM edges whose midpoint lies within 15 m and whose bearing is within 30°. One cnn can map to several segments, and each segment gets its best-overlap cnn.

## 8. Event-aware probing and API budgets

A corridor is **hot** when an active event with `attendance` or `capacity` ≥ 3,000 lies within `hot_radius_m` (default 1.5 km) of one of its watch venues and either:
- it starts within [−1 h, +3 h], or
- it ends within [−1 h, +2 h].

Today `pull.poll` probes all 17 Mapbox legs every 10 min. Hot/cold is a later change to `pull.poll`: poll cold legs less often and hot legs more often, within the same monthly budget. Google uses the hot flag from the start.

| API | Limit | Plan |
|---|---|---|
| Mapbox Directions | 100k requests/month free | 17 legs every 10 min ≈ 73k (`pull.poll` refuses > 90k). |
| Mapbox tiles | 200k tiles/month free, separate quota | 81 tiles every 20 min ≈ 137–175k. |
| TomTom tiles | 200k tiles/month free | 25 tiles, absolute every 10 min + relative every 6 h ≈ 111k. |
| 511 | 60 requests/hour per token | Muni every 90 s (40) + events every 10 min (6), both in `pull.poll`, + WZDx every 30 min (2) = 48/h. Stays under `pull.poll`'s cap of 55; the worker's WZDx call has to count against the same budget. |
| Google Routes | paid SKU (traffic-aware + alternatives + traffic-on-polyline) | Off by default (`GOOGLE_ROUTES_ENABLED=false`). Hot corridors only. Confirm the SKU tier and free cap before turning it on. |
| PredictHQ | plan-limited area and dates | Results are silently clipped to the plan, so an empty result can mean "outside plan". Log `overflow`. |
| DataSF | IP-throttled without a token | Use `DATASF_APP_TOKEN`. |

## 9. Dedupe and time rules

- **Events across sources.** A Giants game shows up in PredictHQ, as a 511 `SPECIAL_EVENT`, and as a DataSF street closure. It counts as the same event when it is within 400 m, starts within 2 h, and either the titles are similar or the starts are within 45 min.
  - Each source's normalized view is kept under `sources.<name>`.
  - Canonical fields are filled by precedence: attendance and rank from PredictHQ, closures from 511 and DataSF, everything else first non-empty.
- **Incidents across sources** (for example an SFMTA closure in both DataSF and WZDx) stay as separate docs. Routing asks "is segment X closed at time T", and a duplicate doesn't change that answer.
- **Times.** Everything is stored as UTC.
  - PredictHQ: times are UTC, except when `timezone` is null (holidays), where they are SF wall-clock.
  - DataSF: SF local, except `*_utc` columns.
  - CHP and 511 schedules: SF local.
  - Mapbox, TomTom, Muni and Google: UTC.

## 10. Code layout and commands

```
ingest/
  pull/  datasf/          unchanged: raw fetchers, `python -m pull` snapshots, `python -m pull.poll` JSONL
  worker/                 built (steps 1-2)
    __main__.py           python -m worker bootstrap | run segments|traffic [--source S] [--dry-run] | schedule
    network.py            GraphML -> edges, DataSF cnn + posted-limit link, direction-aware snapping
    traffic.py            tomtom / mapbox_route / mapbox_tiles / muni readers -> 10-min rows, route ETAs, route plans
    db.py  schema.sql     Tiger + Mongo sinks (idempotent upserts), dry-run sink; schema additions to contracts/
    state.py  geo.py      watermarks + line->segment cache on disk; stdlib geometry + grid index
  tests/                  offline: synthetic graph + JSONL fixtures -> rows (no network, no DB)
```
Still to add (steps 3-5): `incidents.py`, `events.py`, `google.py`, `sumo.py`, following the same reader -> sink shape.

- Dependencies: a new `[db]` extra (`pymongo`, `psycopg[binary]`). The worker reads the GraphML with the standard library; `[osm]` is only needed to pull the graph.
- Env names: `MONGODB_URI`, `TIGER_DATABASE_URL`, `MAPBOX_TOKEN`, `SF511_API_KEY`, `DATASF_APP_TOKEN`, `TOMTOM_API_KEY`, plus new `PREDICTHQ_TOKEN`, `GOOGLE_MAPS_API_KEY`, `GOOGLE_ROUTES_ENABLED`.
- Scheduler: a stdlib loop over a job table (`next_run_at`, `every`). Jobs run one after another, which is fine because a full cycle takes seconds. OSM and the nightly jobs use the same loop with daily or weekly periods.
- Deploy: one small DigitalOcean **droplet** running `python -m worker schedule` under systemd. Use a droplet rather than App Platform because the worker needs `data/raw/osm_drive_graph.graphml`, the `pull.poll` JSONL and its own state on a persistent disk.

## 11. Differences from the reference worker

| Reference | Here | Why |
|---|---|---|
| Tiger tables named apart from the team drafts (`segment_speed_obs`, kph, per-row incident/event logs) | Draft tables and the `AGENTS.md` traffic normalization (10-min buckets, mph, `congestion_ratio`); no incident/event logs | Same vocabulary as the rest of the team; one `traffic_metrics` for every speed source |
| Mongo `_id`s + `windows` only | `AGENTS.md` draft fields (`segment_id`, `source+source_id`, `location`, `start_time/end_time`, `road_segment_ids`) | Other folders already plan around those names |
| Raw payloads in Mongo (TTL) | Raw payloads on disk | M0 is 512 MB |
| Mapbox every 5 min, OD pairs with alternatives | `pull.poll`'s feeds (TomTom, Mapbox corridors + tiles, Muni) loaded from its JSONL | City-wide coverage within free tiers; one fetch path |
| 511 + PredictHQ only | + DataSF closures, permits, dispatch, speed limits, Caltrans, CHP | Already pulled and quality-checked (`TODO.md`) |
| `requests` + APScheduler | Reuse `pull/` stdlib HTTP, stdlib loop | Fewer deps; one fetch path for snapshots and the worker |

Kept from the reference: the midpoint-plus-direction segment matcher, the event store with per-source blocks and precedence, 511 schedule expansion, WZDx "unseen → removed", Google future-departure forecasts, seeds for venue capacity, and the 511 rate limiter that skips instead of blocking.

## 12. Build order

1. **Foundation.** `db.py`, `runlog.py`, `osm_segments`, `datasf_rules` (cnn link + speed limits), seeds, `bootstrap`. Agree the schema (§4–§6) with the team and land it as one `contracts/` PR first.
2. **Traffic history.** `pull.poll` is already collecting, so this step is loaders: the four `traffic_*` jobs read `data/timeseries/*` (whole history on first run, then new lines) into `traffic_metrics`, `route_eta_metrics` and `route_plans`. Move `pull.poll` and the worker to the droplet here so collection stops depending on a laptop.
3. **Closures.** `incidents_datasf`, `incidents_state`, `incidents_live`, and `incidents_511` (511 events are already being collected).
4. **Events.** `predicthq` (built: `worker/events.py`), event dedupe, and hot/cold probing switches on.
5. **Extras.** Google forecasts, PredictHQ features, the SUMO loader for the before/after demo.

## 13. Open decisions

- ~~PredictHQ or Ticketmaster~~: PredictHQ. A Ticketmaster fallback would be one more `normalize` in `worker/events.py`.
- **Schema sign-off (§4–§6).** `ml/` and `api/` read these tables, so agree on them before anything is created. Then update `contracts/tiger_schema.sql` and the `AGENTS.md` data-store tables to match.
- **Google Routes spend.** Enable, or rely on Mapbox `duration_typical` as the "normal routing" baseline?
- **Venue capacities in `seeds/venues.json`.** Approximate public figures; verify them before quoting them in the demo.
