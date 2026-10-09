# App raw history read handoff (opt-in code; migration in flight)

The [DAG migration lane](task_dag.md#1-finish-the-history-migration-before-expanding-persistence)
separates `THREAD_ARCHIVE_BACKFILL`, `THREAD_ARCHIVE_INGEST`, `THREAD_ARCHIVE_READ_CUTOVER`,
`THREAD_ARCHIVE_UI_CUTOVER`, `THREAD_ARCHIVE_OWNERSHIP` and `APP_RAW_HISTORY_RETIRE`.
Bulk import and a catch-up pass completed; live handoff remains in progress. This document does
not claim any live switch has been enabled.
New service input/metadata tables and unrelated app schema changes wait for the ownership capstone.

`ReadSessionEvents` is bounded to 1000 entries and the explicitly configured
Sandbox Service `history_reader_accounts`. A public UUID is not authorization.
The app's service identity is the only configured reader; notification service
and sandboxes cannot call it. The app's `history_reads_enabled` switch is off
by default. When enabled, `/events`, `/events/stream` and expanded raw observation entries read the service and
read a fixed committed service prefix rather than chasing the independently advancing app cursor.
A requested resume cursor beyond the service prefix remains an explicit error; reads never silently
fall back to app rows. Thread folds, chronological observation metadata and feed state still come from the app.
This is therefore a staged **read migration**, not permission for agents to
read Sessions or permission to delete the app raw tables.

Before enabling: import existing rows via #9460 (including deleted sandboxes),
resolve any active legacy rows with NULL Sandbox UID, prove shadow copier
parity and handoff under concurrent writes, deploy the service reader first,
then enable the app read switch. Confirm paging, SSE replay/resume, old native
frames, and inability to read raw history with a non-app ServiceAccount.
A follow-on change must make the service the durable write authority and
move remaining app raw observation _metadata_ reads without breaking app-only folds.
Until then keep app event ingestion and do not remove its tables.

## Executable preflight and concurrent-write gate

Use the [catch-up/handoff runbook](../sandbox_service/session_history/CUTOVER.md) and its bounded,
read-only verifier for fixed-watermark archive samples and bounded runner overlap evidence.
The operator explicitly chose not to repeat a full historical scan: import receipts, all-Session
watermarks and selected boundary windows are the migration evidence, with residual risk of an
undetected interior mismatch. Sample success must not be reported as full historical parity. The verifier
does not assign legacy UIDs or implement the consumer handoff. A one-time cursor match while app
and service ingest independently does not make the fail-closed read switch safe: coordinate the
app read/projection cursor with the service's committed prefix before switching. Keep runner
execution and at least one ingestion path active; fence only the old app consumer at its recorded
final cursor under a reviewed handoff. No global quiet period or automatic stale-table rollback.

## Draft app consumer handoff primitives (not a rollout switch)

The draft adds a service-watermark-bounded raw reader and `HistoryProjector.project_batch`.
The projector resumes the existing `ThreadCheckpoint`, folds at most 128 service Events under
an app ingestion lease, and advances UI state/checkpoint atomically without writing app `Event`
rows. Replays resume from the committed UI position; fold failures leave the checkpoint unchanged
and cannot block the independent service raw ingester. It is deliberately not scheduled by app
startup. No configuration default or deployed flag changes in this draft.

Before wiring or enabling it:

1. Implement a durable ingestion-source fence that mixed-version app replicas honor. The existing
   sandbox lease fences individual batches but does not by itself prevent an old replica from
   reacquiring a lease and resuming runner-backed ingestion. Capture the final app raw cursor under
   that fence; wait until the service covers it before releasing the service-backed consumer.
2. Add the resumable supervisor, retry/error/lag reporting and discovery for all retained Threads,
   including deleted Sandboxes. It must work with runners unreachable. Do not make a fresh runner
   attachment a prerequisite for archive projection.
3. Move chronological observation metadata and Thread/feed cursors/lifecycle away from app raw
   `Event` rows. Preserve UI checkpoint/source/epoch and existing Thread URLs. The raw SSE path now
   waits for a terminal app suffix instead of spinning or prematurely ending while service lags;
   this is not yet service-owned lifecycle evidence.
4. Test owner takeover, replica restart and migration interruption end-to-end, then perform the
   reviewed cutover with app raw tables retained. Never enable both competing projection paths.

This draft is useful before shadow convergence, but does not satisfy the archive-ownership gate.
