# Ingest data sources: plan & backlog

Status: ✅ raw pull working + quality-checked · 🟡 code ready, waiting on a key · ⬜ to do · 🔑 needs a key (put it in `ingest/.env`)

Pull: `.venv/Scripts/python -m pull [static|planned|live|<source>]` → `ingest/data/raw/<source>.json`
Check: `.venv/Scripts/python -m pull.check`

## 1. Static road rules (refresh nightly)
| # | What | Source (`pull` name) | Status |
|---|------|--------|--------|
| 1 | Road graph: intersections, geometry, one-ways | OpenStreetMap via OSMnx (`osm_drive_graph`, also saved as GraphML) | ✅ |
| 1b | Turn restrictions (OSMnx drops these) | OpenStreetMap via Overpass (`osm_turn_restrictions`) | ✅ |
| 2 | SF street network, keyed by SF street ID (`cnn`) | DataSF `3psu-pn9h` (`streets`) | ✅ |
| 3 | Speed limits (incl. school zones) | DataSF `3t7b-gebn` (`speed_limits`) | ✅ |
| 4 | Low bridges / underpasses | DataSF `eb2x-6eay` (`clearance_heights`; no `cnn`, match by location) | ✅ |
| 5 | Parking regulations | DataSF `hi6h-neyh` (`parking_regulations`) | ✅ |
| 6 | Tow-away zones | DataSF `ynvq-waab` (`tow_away_zones`) | ✅ |
| 7 | Street sweeping schedule | DataSF `yhqp-riqs` (`street_sweeping`) | ✅ |

## 2. Planned closures, permits, events (poll every 15–60 min)
| # | What | Source (`pull` name) | Status |
|---|------|--------|--------|
| 8 | Temporary street closures, incl. special events (still in effect or upcoming) | DataSF `8x25-yybr` (`street_closures`) | ✅ |
| 9 | Street-use permits (active now → +30 days) | DataSF `b6tj-gt35` (`street_use_permits`) | ✅ |
| 10 | Utility excavation permits (active now → +30 days) | DataSF `smdf-6c45` (`excavation_permits`) | ✅ |
| 11 | Temporary no-parking signs / street space permits | DataSF `sftu-nd43` (`parking_signs`) | ✅ |
| 12 | Freeway and state-route lane closures | Caltrans D4 feed (`caltrans_lane_closures`) | ✅ |
| 13 | Events: type, time, expected attendance | PredictHQ 🔑 (probably paid; check pricing). Fallback: Ticketmaster Discovery API 🔑 (free) | ⬜ (blocked on decision + key) |

## 3. Live conditions (poll every 1–5 min)
| # | What | Source (`pull` name) | Status |
|---|------|--------|--------|
| 14 | Real-time police dispatch calls (~20 min lag) | DataSF `gnap-fj3t` (`police_dispatch`) | ✅ |
| 15 | Traffic incidents, closures, construction (Bay Area; ~100 events, one request) | 511.org 🔑 (`sf511_traffic_events`; polled into `timeseries/sf511_events` when new/updated) | ✅ |
| 15b | Muni vehicle positions every 90 s → bus speeds on most major streets | 511.org 🔑 (`sf511_muni_vehicles`; `timeseries/muni_vehicles`; speeds derived from consecutive fixes) | ✅ collecting |
| 16 | Freeway crashes and hazards | CHP feed (`chp_incidents`); sometimes served truncated, parsed entry by entry | ✅ |
| 17 | Live speed + congestion per road segment on 9 corridors (17 routes), every 10 min → time series | Mapbox Directions `driving-traffic` 🔑 (`python -m pull.poll`, corridors in `pull/corridors.py`) | ✅ collecting |
| 17b | Longer multi-waypoint venue loops (up to 25 waypoints, same request cost) | Mapbox Directions | ⬜ |
| 17c | **City-wide speed (km/h) + closure flag on every road line**, zoom 13 (25 tiles): absolute every 10 min, relative (fraction of free-flow) every 6 h | TomTom Traffic API vector flow tiles 🔑 (`tomtom_flow`; ~111k of 200k free tiles/month) | ✅ collecting |
| 17d | Congestion level on every road line incl. residential, zoom 14 (81 tiles, 63 with roads) every 20 min | Mapbox `mapbox-traffic-v1` tiles (`mapbox_traffic`; ~137–175k of 200k free tiles/month, separate from Directions) | ✅ collecting |

## 4. Simulation
| # | What | Source | Status |
|---|------|--------|--------|
| 18 | SUMO road network | SUMO OpenStreetMap import (needs SUMO installed) | ⬜ |

## Data notes from the quality checks (read before writing the ingestion worker)
- **`cnn` is either a street segment or an intersection.** Permits use both (street-use: 4,558 segments + 1,022 intersections; excavation: 2,710 + 685). Join intersections via `streets.f_node_cnn` / `t_node_cnn`.
- **Speed limits:** only ~23% of segments have a posted limit; `0` = unposted (CA default 25 mph); `99` = state freeway/ramp (US-101, I-280), not a real limit. OSM `maxspeed` covers ~26% of edges.
- **Composite keys:** excavation permits are one row per permit *per segment* (key `permit_number+cnn`); parking signs reuse `signid` across segments/sides (key `signid+cnn+sideofstreet`).
- **Police dispatch:** sensitive calls (~27%) have no location by design; the feed holds ~48 h plus a few long-open older calls.
- **CHP:** a few incidents are `0:0` (mostly construction assists). Times are Pacific local.
- **Street closures** carry true UTC in `start_utc`/`end_utc`; every other DataSF timestamp is SF local with no offset.
- Some Windows cert stores break TLS to overpass-api.de; `pull/http.py` uses certifi's bundle when installed.

## Speed history (target data for forecasting models)
- **Nothing free gives historical speeds for SF city streets.** Start polling now so history accumulates (~1 h for zero-shot forecasts, 2–4 weeks to evaluate/fine-tune, months to learn event effects).
- Mapbox free tier: 100k requests/month → 17 routes every 10 min (~73k). `pull.poll` refuses schedules over 90k unless `--allow-paid`.
- Free historical freeway speeds exist (Caltrans PeMS / LargeST Bay Area) if we want pretraining/eval data; not SF surface streets.
- 511 token limit is ~60 requests/hour: Muni every 90 s (40/h) + events every 10 min (6/h). `pull.poll` refuses schedules over 55/h.
- Polling runs wherever it's started; a laptop that sleeps leaves gaps (`pull.check` reports them). Move to DigitalOcean with the ingestion worker.

### Coverage (2026-09-26, share of SF's 1,158 miles of drivable road, from the OSM graph)
| Road type | Miles | Mapbox routes (exact speed) | TomTom tiles (speed) | Mapbox tiles (congestion level) | Muni (night) | Combined |
|---|---|---|---|---|---|---|
| Freeway | 67 | 0.2% | 100% | 100% | 1.8% | 100% |
| Trunk/primary | 106 | 18.6% | 99.8% | 100% | 8.5% | 100% |
| Secondary | 133 | 6.0% | 100% | 100% | 7.4% | 100% |
| Tertiary | 136 | 2.0% | 92.9% | 100% | 4.0% | 100% |
| Residential/other | 716 | 1.2% | 35.6% | 99.8% | 1.6% | 99.9% |
| All | 1,158 | 3.4% | 59.4% | 99.9% | 3.2% | 99.9% |

- Actual speed (km/h) on ~59% of road length (TomTom); congestion level only on the rest (Mapbox tiles), to be converted to mph using roads where both Mapbox congestion and an exact speed exist (Mapbox routes).
- TomTom's residential gap is missing data, not zoom: zoom 13/14/15 all gave the same coverage in the Sunset and Mission tests.
- Mapbox residential lines were ~all "low" at 2 AM; confirm in daytime that they vary (real signal, not a default).
- Measured by sampling every ~25 m along each OSM road and checking for a source's line within ~15–45 m, so parallel roads can be slightly overcounted.

## Ingestion worker (`python -m worker`, design: `DESIGN.md`)
- ✅ OSM edges → Mongo `road_segments` (`segment_id` = `u-v-key`), linked to DataSF `cnn` (edge midpoint within 15 m) with that cnn's posted limit. Real SF graph: 27,632 edges, 99% get a cnn, 6,685 a posted limit.
- ✅ `pull.poll` JSONL → Tiger `traffic_metrics` (matches that break a connected path are pruned) per AGENTS.md "Traffic data normalization" (10-min buckets; `tomtom`, `mapbox_route`, `mapbox_tiles`, `muni`), incremental per-source watermark in `data/worker/state.json`, only closed buckets written.
- ✅ Mapbox corridor ETAs → Tiger `route_eta_metrics` (new table, `worker/schema.sql`); probe geometry → Mongo `route_plans`.
- ⬜ Mapbox tile ratios calibrated per road class (uses the uncalibrated 0.1 / 0.4 / 0.65 / 0.85 until then).
- ✅ Closures/incidents → Mongo `road_incidents` (`python -m worker run incidents`): DataSF street closures, street-use + excavation permits, Caltrans lane closures, CHP, police dispatch (traffic calls only). `is_closure` = closed to traffic. Validation → `data/quarantine/<source>.jsonl`; cross-source dedupe; optional geocoding (`GEOCODER=mapbox`). Ported from `ingestion-workers-v1` with fixes (Caltrans keyed per closure window, non-traffic police calls dropped, parking signs not stored). Real run: 17.6k docs, 0 rejected.
- ⬜ 511 traffic events + WZDx → `road_incidents` (events already collected by `pull.poll`).
- ⬜ Events + venues (blocked on PredictHQ vs Ticketmaster).
- ⬜ Google forecasts, SUMO loader.

## Open decisions
- PredictHQ vs Ticketmaster, depending on PredictHQ pricing.
- Keep or drop the ~1-day-lagged feeds still in the DataSF registry but not pulled: fire/EMS calls (`nuek-vuh3`), 311 blocked-street/road-defect cases (`vw6y-z8j6`).

## Deferred
- **Destination status = traffic demand** (who is heading where, when). Not a feed: derive it from users' trip search requests + event data (#13) + historical patterns. Also serves as SUMO trip demand. Likely owned by `ml/`.

## Dropped
- Weather, BART, freeway and city-street speed feeds (PeMS, TomTom, HERE), pavement condition.
