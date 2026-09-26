-- Tiger Data (service transPEAKtation, dp0coukufh, db tsdb) schema. Idempotent.
-- Apply: psql "$TIGER_DATABASE_URL" -f contracts/tiger_schema.sql  (or: tiger db query dp0coukufh --file ...)
-- road_segment_id -> Mongo road_segments.segment_id; vehicle_id -> Mongo vehicles.vehicle_id.

-- Model predictions per road segment (ml/ writes).
CREATE TABLE IF NOT EXISTS prediction_metrics (
    time TIMESTAMPTZ NOT NULL,
    model_version TEXT NOT NULL,
    event_id TEXT,
    road_segment_id TEXT NOT NULL,
    prediction_horizon_min INTEGER,
    current_speed_mph DOUBLE PRECISION,
    predicted_speed_mph DOUBLE PRECISION,
    predicted_delay_sec DOUBLE PRECISION,
    predicted_demand DOUBLE PRECISION,
    confidence DOUBLE PRECISION
) WITH (tsdb.hypertable, tsdb.partition_column='time');

-- Observed traffic speed + congestion per road segment (Mapbox/Google Routes, 511, SUMO replay).
CREATE TABLE IF NOT EXISTS traffic_metrics (
    time TIMESTAMPTZ NOT NULL,
    road_segment_id TEXT NOT NULL,
    source TEXT NOT NULL,
    speed_mph DOUBLE PRECISION,
    free_flow_speed_mph DOUBLE PRECISION,
    travel_time_sec DOUBLE PRECISION,
    congestion_ratio DOUBLE PRECISION   -- 1 - speed/free_flow; 0 = free flow, 1 = stopped
) WITH (tsdb.hypertable, tsdb.partition_column='time', tsdb.segmentby='road_segment_id');

-- AV fleet telemetry. Vehicle identity/config lives in Mongo.
CREATE TABLE IF NOT EXISTS av_positions (
    time TIMESTAMPTZ NOT NULL,
    vehicle_id TEXT NOT NULL,
    trip_id TEXT,
    status TEXT,                         -- idle | en_route_pickup | on_trip | charging | offline
    lat DOUBLE PRECISION NOT NULL,
    lon DOUBLE PRECISION NOT NULL,
    heading_deg DOUBLE PRECISION,
    speed_mph DOUBLE PRECISION,
    battery_pct DOUBLE PRECISION,
    road_segment_id TEXT
) WITH (tsdb.hypertable, tsdb.partition_column='time', tsdb.segmentby='vehicle_id');

-- Observed rider demand vs supply per zone (predictions go in prediction_metrics).
CREATE TABLE IF NOT EXISTS demand_metrics (
    time TIMESTAMPTZ NOT NULL,
    zone_id TEXT NOT NULL,
    event_id TEXT,
    trip_requests INTEGER,
    trips_started INTEGER,
    available_vehicles INTEGER,
    avg_wait_sec DOUBLE PRECISION
) WITH (tsdb.hypertable, tsdb.partition_column='time', tsdb.segmentby='zone_id');

-- SUMO / what-if simulation output, per run and segment.
CREATE TABLE IF NOT EXISTS simulation_metrics (
    time TIMESTAMPTZ NOT NULL,           -- simulated wall-clock time
    run_id TEXT NOT NULL,
    scenario TEXT,
    road_segment_id TEXT NOT NULL,
    vehicle_count INTEGER,
    avg_speed_mph DOUBLE PRECISION,
    avg_delay_sec DOUBLE PRECISION,
    throughput_vph DOUBLE PRECISION
) WITH (tsdb.hypertable, tsdb.partition_column='time', tsdb.segmentby='run_id');

-- "Latest value for X" lookups.
CREATE INDEX IF NOT EXISTS prediction_metrics_segment_time_idx ON prediction_metrics (road_segment_id, time DESC);
CREATE INDEX IF NOT EXISTS traffic_metrics_segment_time_idx ON traffic_metrics (road_segment_id, time DESC);
CREATE INDEX IF NOT EXISTS av_positions_vehicle_time_idx ON av_positions (vehicle_id, time DESC);
CREATE INDEX IF NOT EXISTS demand_metrics_zone_time_idx ON demand_metrics (zone_id, time DESC);
CREATE INDEX IF NOT EXISTS simulation_metrics_run_segment_time_idx ON simulation_metrics (run_id, road_segment_id, time DESC);
