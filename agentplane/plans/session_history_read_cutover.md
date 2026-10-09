# App raw history read handoff (opt-in code; migration in flight)

The [DAG migration lane](task_dag.md#1-finish-the-history-migration-before-expanding-persistence)
separates `THREAD_ARCHIVE_BACKFILL`, `THREAD_ARCHIVE_INGEST`, `THREAD_ARCHIVE_READ_CUTOVER`,
`THREAD_ARCHIVE_UI_CUTOVER`, `THREAD_ARCHIVE_OWNERSHIP` and `APP_RAW_HISTORY_RETIRE`.
Backfill is reported in progress; this document does not claim any live switch has been enabled.
New service input/metadata tables and unrelated app schema changes wait for the ownership capstone.

`ReadSessionEvents` is bounded to 1000 entries and the explicitly configured
Sandbox Service `history_reader_accounts`. A public UUID is not authorization.
The app's service identity is the only configured reader; notification service
and sandboxes cannot call it. The app's `history_reads_enabled` switch is off
by default. When enabled, `/events`, `/events/stream` and expanded raw observation entries read the service and
fail closed if its prefix lags the app's known cursor: they never silently
fall back to another source. Thread folds, chronological observation metadata and feed state still come from the app.
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
read-only verifier for fixed-watermark archive parity and runner overlap evidence. The verifier
does not assign legacy UIDs or implement the consumer handoff. A one-time cursor match while app
and service ingest independently does not make the fail-closed read switch safe: coordinate the
app read/projection cursor with the service's committed prefix before switching. Keep runner
execution and at least one ingestion path active; fence only the old app consumer at its recorded
final cursor under a reviewed handoff. No global quiet period or automatic stale-table rollback.
