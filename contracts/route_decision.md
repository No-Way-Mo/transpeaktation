# Route decision: `api/` ↔ `ml/`

How `ml/` plugs into trip planning. `api/` gathers everything known about the trip at the chosen time and sends it
to `ml/`; `ml/` forecasts congestion from it (and from any history it reads itself), routes on that forecast plus
demand, and returns the optimized route, which the rider sees as the transPEAKtation route. Changing the model
never needs changes in `web/` or `api/`.

`POST {ML_URL}/decide`, called on every `/plan` when `ML_URL` is set in `api/.env`. Unset, down, slower than 8 s,
or an off-contract answer: `/plan` keeps its own heuristic pick, and `data.decision` in the `/plan` response says
which one was used (`ml:<model>` or `heuristic (...)`).

Optional: `ml/` may also write its per-segment forecasts to Tiger `prediction_metrics` (schema:
`tiger_schema.sql`) for the fleet dashboard / transparency page. `/plan` reads them back and sends them in
`context.predictions`, so they are available to the decision too, but nothing requires them.

## Request (`api/` → `ml/`), JSON

```jsonc
{
  "version": 1,
  "at": "2026-09-20T01:30:00+00:00",        // the moment the inputs describe (earliest departure), UTC
  "mode": "now" | "depart" | "arrive",
  "replay": false,                            // true: a simulated past trip (demo); inputs are as of `at`
  "origin": {"lon": -122.4075, "lat": 37.788},
  "destination": {"lon": -122.3893, "lat": 37.7786},
  "candidates": [{                            // the routing provider's routes (Mapbox, OSRM fallback), fastest first
    "index": 0,
    "departs_at": "2026-09-20T01:30:00+00:00",
    "dur_sec": 720, "dur_typical_sec": 600,   // provider ETA; typical = usual traffic (Mapbox only, else null)
    "dist_m": 2600,
    "coords": [[37.788, -122.4075], ...],     // [lat, lon]
    "road_segment_ids": ["65333347-6319310995-0", ...],   // OSM edges u-v-key, in driving order
    "congestion": ["low", "heavy", ...] | null,           // per coords pair (Mapbox driving-traffic only)
    "heuristic": {                            // api/'s own estimate, for comparison / fallback
      "dur_sec": 2402, "delay_sec": 1682,
      "breakdown": {"events_sec": 482, "incidents_sec": 1200, "traffic_sec": 0},
      "events": ["Giants vs. Dodgers at Oracle Park"], "incidents": ["Road closure on Dreamforce 2026"],
      "blocked": true
    }
  }],
  "context": {                                // everything stored for these segments at `at` (see AGENTS.md Data stores)
    "events": [{"id", "title", "category", "venue", "lat", "lon", "start", "end", "attendance", "capacity", ...}],
    "incidents": [{"source", "source_id", "category", "is_closure", "start_time", "end_time", "road_segment_ids", "details"}],
    "traffic": {"kind": "live" | "observed" | "typical",   // now / what was seen then (replay) / weekly average (future)
                "rows": [{"road_segment_id", "source", "time", "speed_mph", "free_flow_speed_mph", "congestion_ratio"}]},
    "predictions": [{"road_segment_id", "time", "predicted_delay_sec", "model_version"}],  // ml/'s own stored forecasts, if any
    "segment_lengths_m": {"65333347-6319310995-0": 84.2, ...}
  },
  "demand": {                                 // other riders going to about the same place (Mongo trips)
    "trips_to_destination": 12,               // null if the database is unavailable
    "radius_m": 400,
    "window": ["2026-09-20T00:30:00+00:00", "2026-09-20T02:30:00+00:00"]   // their departure times
  }
}
```

Times are ISO 8601 with offset. The request carries data for the trip's time only; for forecasting, `ml/` reads the
history it needs directly from Tiger (`traffic_metrics`, every 10 min per segment) and Mongo (`trips`, `events`).

## Response (`ml/` → `api/`), JSON, HTTP 200

Pick one of the candidates:

```json
{"model": "congestion-v0", "choice": {"candidate": 1}, "predicted_sec": 1301,
 "reasons": ["Skips the Dreamforce closure on Howard St.", "12 other riders are heading to Oracle Park."]}
```

Or route it yourself: 1 to 23 `[lon, lat]` points to pass through in order (e.g. every few segments of your own
path on the OSM graph). `api/` asks Mapbox for the route through them, so the rider still gets geometry and
turn-by-turn directions:

```json
{"model": "congestion-v0", "choice": {"waypoints": [[-122.4050, 37.7850], [-122.3990, 37.7800]]},
 "predicted_sec": 1180, "reasons": ["Avoids the 4th St crowd by taking 3rd St."]}
```

| Field | Rules |
|---|---|
| `model` | non-empty name/version; shown as `ml:<model>` |
| `choice` | `{"candidate": i}` with `0 <= i < len(candidates)`, or `{"waypoints": [...]}` inside San Francisco |
| `predicted_sec` | your door-to-door time for the chosen route, seconds, `0 < x < 21600` |
| `reasons` | optional, up to 3 short strings; they replace the explanation on the transPEAKtation card |

`api/` does not re-check a waypoint route against closures: `ml/` owns that choice. The other candidates are still
shown to the rider as the normal routes.

## Try it

`ML_URL=http://localhost:8100` in `api/.env` (or the environment), run `ml/`'s server on that port, plan a trip,
and check `data.decision` in the `/plan` response. Its heuristic comparison lives in `api/app/model.py`.
