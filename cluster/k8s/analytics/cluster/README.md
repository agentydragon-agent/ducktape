# Shared analytics ClickHouse

One shard with two replicated ClickHouse servers and a three-member Keeper
quorum, all on the OVH HDD data tier. The cluster is intentionally independent
of Langfuse's chart-owned ClickHouse so applications can migrate one at a time.

The first tenant is `aiquota`:

- `aiquota.raw_http_observations` preserves bounded exact upstream response
  bytes (base64 + SHA-256) alongside normalized JSON.
- `aiquota.aiquota_windows` provides typed quota-window history for Grafana.
- typed quota windows retain five years of hot/queryable data;
- raw response bodies retain one year in ClickHouse, with the exact bounded
  bytes and integrity metadata available for inspection;
- a ClickHouse materialized view projects the raw row's quota-window array into
  the typed table, so each collector snapshot is one atomic insert rather than
  two independently retried writes.

The versioned `clickhouse-aiquota-schema-v1` Job applies the tenant schema with
`ON CLUSTER analytics`, so every replica receives the same database, tables,
and materialized view without depending on ClickHouse startup configuration
mount ordering. Schema Jobs are retained after completion as rollout evidence.
A future schema revision must use a new Job name (for example `v2`) so
Kubernetes never has to mutate a completed Job template.

Each tenant gets its own database, least-privilege users, credentials, quotas,
and query profile. A later Langfuse migration can therefore add a separate
`langfuse` database without sharing aiquota's insert or Grafana credentials.

Applications receive separate insert-only credentials; Grafana receives a
read-only account. NetworkPolicy admits only those named consumers plus
same-namespace administration and Alloy metrics scraping.
