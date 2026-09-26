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
| 15 | Traffic incidents, closures, Muni vehicles | 511.org 🔑 (`sf511_traffic_events`, `sf511_muni_vehicles`; free; ~60 req/hr per token) | 🟡 response shapes unverified until we have a key |
| 16 | Freeway crashes and hazards | CHP feed (`chp_incidents`); sometimes served truncated, parsed entry by entry | ✅ |
| 17 | Candidate routes, polyline, baseline + live ETA, per-segment traffic | Mapbox Directions or Google Routes 🔑 (pick one) | ⬜ (blocked on decision + key) |

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

## Integration work (ingestion worker step, not started)
- Link DataSF segments (`cnn`) to OSM roads by location (OSMnx nearest-edge match); redo on each refresh.
- Normalize, dedupe, geocode, write to MongoDB / Tiger Data.

## Open decisions
- Mapbox vs Google Routes (only one).
- PredictHQ vs Ticketmaster, depending on PredictHQ pricing.
- Keep or drop the ~1-day-lagged feeds still in the DataSF registry but not pulled: fire/EMS calls (`nuek-vuh3`), 311 blocked-street/road-defect cases (`vw6y-z8j6`).

## Deferred
- **Destination status = traffic demand** (who is heading where, when). Not a feed: derive it from users' trip search requests + event data (#13) + historical patterns. Also serves as SUMO trip demand. Likely owned by `ml/`.

## Dropped
- Weather, BART, freeway and city-street speed feeds (PeMS, TomTom, HERE), pavement condition.
