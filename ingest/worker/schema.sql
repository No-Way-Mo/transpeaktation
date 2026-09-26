-- Ingestion worker additions to contracts/tiger_schema.sql (proposal: moves into contracts/
-- once the team agrees, see ingest/DESIGN.md section 6). Idempotent; applied after the
-- contract file by `python -m worker bootstrap`.

-- Idempotent writes: reloading a day of JSONL updates rows instead of duplicating them.
CREATE UNIQUE INDEX IF NOT EXISTS traffic_metrics_uq ON traffic_metrics (road_segment_id, source, time);

-- Route-level ETAs, live and forecast. Mapbox corridor probes now; Google future-departure
-- forecasts later (departure_time > time). Compare a forecast with the live rows observed then.
CREATE TABLE IF NOT EXISTS route_eta_metrics (
    time TIMESTAMPTZ NOT NULL,              -- when we asked
    corridor_id TEXT NOT NULL,
    direction TEXT NOT NULL,                -- ab | ba
    provider TEXT NOT NULL,                 -- mapbox | google
    route_idx SMALLINT NOT NULL,            -- 0 = provider's pick, 1+ = alternatives
    departure_time TIMESTAMPTZ NOT NULL,    -- = time for live; later for forecasts
    duration_sec DOUBLE PRECISION,
    typical_duration_sec DOUBLE PRECISION,  -- Mapbox duration_typical (usual traffic, not free flow)
    static_duration_sec DOUBLE PRECISION,   -- Google staticDuration (no traffic)
    distance_m DOUBLE PRECISION,
    route_plan_id TEXT,                     -- Mongo route_plans._id
    event_id TEXT                           -- event that made the corridor hot, if any
) WITH (tsdb.hypertable, tsdb.partition_column='time', tsdb.segmentby='corridor_id');
CREATE UNIQUE INDEX IF NOT EXISTS route_eta_metrics_uq
    ON route_eta_metrics (corridor_id, direction, provider, route_idx, departure_time, time);
