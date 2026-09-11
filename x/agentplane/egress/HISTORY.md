# Diagnostic decision history

`DecisionLog.record` captures immutable admission records into a bounded queue without database IO.
One task drains up to 100 at a time, using an async SQLAlchemy/asyncpg engine with bounded pool,
connect and command waits. Each batch gets three attempts with exponential backoff; retry reuses
its event IDs and decision timestamps. An acknowledgement lost after commit may increment the
failure count but cannot insert a duplicate. `acknowledged` counts producer events, not newly
inserted rows. Cancellation or exhausted retries can count an event as lost even if an ambiguous
commit persisted it; the counters describe producer knowledge, not proof of database absence.

The database has its own Alembic version table and migration advisory lock. The proxy has no
startup migration path. Staging and testing each own a CNPG database and a separate migration
Job/Flux gate. The new migration image must be published and its ImagePolicy advance before
first deployment; the checked-in initial tag is a bootstrap placeholder. Schema rollouts must
remain compatible with the old proxy while its replacement waits on the migration gate.

Seven-day retention is a visibility bound, not a promise that physical rows disappear precisely
at expiry. Indexed cleanup deletes at most 1,000 expired rows after each batch or idle-minute
wake. Concurrent cleanup skips locked rows. This small diagnostic workload uses indexed deletion
rather than time partitions: there is no measured volume justifying partition management, and
UUID idempotence remains global. Monitor database size and cleanup failures; sustained ingestion
beyond cleanup capacity requires revisiting that choice. This is not tamper-evident auditing:
the application database owner can insert and delete diagnostic records.

`/healthz.decisionHistory` reports accepted/acknowledged counts, loss by overflow/unavailability/
expiry/shutdown, write/cleanup failures, queue depth, writer-running state, and last write
availability (`null` before a write attempt). DB health does not change the enforcement probe
status. Counters are per-process and reset on restart. The list API uses shared committed rows;
queued admissions can be absent, and a database read error is a 503 rather than an empty list.

Names are diagnostic identifiers, not credential values. Host and method lengths are bounded;
paths are always omitted, including paths of denied requests. Sanitizing arbitrary path tokens
cannot guarantee secrecy. No request/response bodies, headers, query strings, raw exceptions or
raw Kubernetes resources enter the decision record. Unauthenticated attempts have no claimed
sandbox identity. Verified UIDs are snapshots, not foreign keys to live Kubernetes objects.

The event/producer IDs and connection ID support correlation, not global causal order. The
legacy `at` API field maps to `decided_at`; `ingested_at` is the transaction insertion timestamp.
Admin reads order the limited recent window by `decided_at,event_id`, oldest first. Sandbox-name
lookups can include earlier incarnations with that name; each row preserves its verified UID.

Replica count, informer status writes and policy freshness/rolling drain behavior are unchanged.
Shared diagnostic history does not make multi-replica enforcement safe.
