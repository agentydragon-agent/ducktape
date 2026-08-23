CREATE DATABASE IF NOT EXISTS aiquota;

CREATE TABLE IF NOT EXISTS aiquota.raw_http_observations
(
  event_id UUID,
  schema_version UInt16,
  dataset LowCardinality(String),
  source LowCardinality(String),
  observed_at DateTime64(3, 'UTC'),
  ingested_at DateTime64(3, 'UTC'),
  status_code UInt16,
  content_type LowCardinality(String),
  raw_body_base64 String CODEC(ZSTD(6)),
  raw_body_sha256 FixedString(64),
  raw_body_size_bytes UInt32,
  raw_body_truncated Bool,
  quota_windows Array(Tuple(
    window_name String,
    used_percent Float64,
    remaining_percent Float64,
    reset_at Nullable(DateTime64(3, 'UTC')),
    reset_seconds Float64,
    window_seconds Float64,
    extra_spend_enabled Nullable(Bool),
    extra_spend_limit_usd Nullable(Float64),
    extra_spend_used_usd Nullable(Float64),
    extra_spend_utilization Nullable(Float64)
  )),
  normalized_body String CODEC(ZSTD(6)),
  error String CODEC(ZSTD(3))
)
ENGINE = ReplicatedMergeTree('/clickhouse/tables/{shard}/aiquota/raw_http_observations', '{replica}')
PARTITION BY toYYYYMM(observed_at)
ORDER BY (dataset, source, observed_at, event_id)
TTL observed_at + INTERVAL 1 YEAR DELETE;

CREATE TABLE IF NOT EXISTS aiquota.aiquota_windows
(
  event_id UUID,
  observed_at DateTime64(3, 'UTC'),
  provider LowCardinality(String),
  window_name LowCardinality(String),
  used_percent Float64,
  remaining_percent Float64,
  reset_at Nullable(DateTime64(3, 'UTC')),
  reset_seconds Float64,
  window_seconds Float64,
  extra_spend_enabled Nullable(Bool),
  extra_spend_limit_usd Nullable(Float64),
  extra_spend_used_usd Nullable(Float64),
  extra_spend_utilization Nullable(Float64)
)
ENGINE = ReplicatedMergeTree('/clickhouse/tables/{shard}/aiquota/aiquota_windows', '{replica}')
PARTITION BY toYYYYMM(observed_at)
ORDER BY (provider, window_seconds, window_name, observed_at, event_id)
TTL observed_at + INTERVAL 5 YEAR DELETE;

CREATE MATERIALIZED VIEW IF NOT EXISTS aiquota.aiquota_windows_mv
TO aiquota.aiquota_windows
AS SELECT
  event_id,
  observed_at,
  source AS provider,
  w.window_name AS window_name,
  w.used_percent AS used_percent,
  w.remaining_percent AS remaining_percent,
  w.reset_at AS reset_at,
  w.reset_seconds AS reset_seconds,
  w.window_seconds AS window_seconds,
  w.extra_spend_enabled AS extra_spend_enabled,
  w.extra_spend_limit_usd AS extra_spend_limit_usd,
  w.extra_spend_used_usd AS extra_spend_used_usd,
  w.extra_spend_utilization AS extra_spend_utilization
FROM aiquota.raw_http_observations
ARRAY JOIN quota_windows AS w;
