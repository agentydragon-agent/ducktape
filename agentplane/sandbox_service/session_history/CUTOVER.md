# History catch-up and handoff preflight

This runbook does not authorize a live change. Keep app ingestion running while importing and
verifying. No global pause of runner execution is required. Do not start a second importer while
the current one is running, fill a legacy Sandbox UID from a matching name, or enable service reads
merely because the first import exits successfully.

## 1. Record primary watermarks and inventory

Discover the current primary instead of assuming `postgres-1`:

```bash
kubectl get pods -n agentplane-staging \
  -l 'cnpg.io/cluster=postgres,cnpg.io/instanceRole=primary' -o name
kubectl get sandboxes.agents.x-k8s.io -n agentplane-staging \
  -o custom-columns='NAME:.metadata.name,UID:.metadata.uid,MODE:.spec.operatingMode,DELETING:.metadata.deletionTimestamp'
```

Run the following in `app` on that primary with `psql -X -v ON_ERROR_STOP=1`. Preserve the results
locally with their timestamp; do not commit environment-specific evidence or database credentials.
If `reading_replica` is true, rediscover the primary. A replica snapshot is not a cutover watermark.

```sql
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '10s';
SET LOCAL lock_timeout = '2s';
SELECT clock_timestamp() AS observed_at, pg_is_in_recovery() AS reading_replica;
SELECT l.id, l.sandbox, l.session_id AS app_session_reference,
       COALESCE((SELECT e.cursor FROM event e WHERE e.thread_id = l.id
                 ORDER BY e.cursor DESC LIMIT 1), 0) AS through
FROM event_log l ORDER BY l.id;
COMMIT;
```

In `sandbox_service`, capture `id`, `sandbox_namespace`, `sandbox_name`, `sandbox_uid`,
`runner_session_id`, `source_id`, and `last_cursor` from `session_history`, using the same read-only
transaction/timeouts and primary check. Join inventories by the public UUID (`event_log.id`), not
by runner locator. New service-created Sessions use public UUIDs in the app but private `r-UUID`
runner locators. Re-enumerate at handoff: Sessions created during a UUID-ordered pass can be missed.

Classify every source Session: matching live incarnation; live name but missing/mismatched UID;
or no current Sandbox. A matching UID still requires runner Session discovery. For absent runners,
retain and verify app history; do not depend on replay from a deleted runner. Suspended runners are
not evidence of completed history. Account separately for live Sandboxes with no app history.

## 2. Finish the first import, then explicitly catch up

Record the current Job's successful completion and final log summary. Failures/conflicts are
blockers; a Running Pod or matching Session counts is not success. Use the existing
[checkpoint-resuming importer](BACKFILL.md), not a new copy implementation. Prepare a new named,
one-shot Job from the reviewed backfill manifest/image and the same approved database bindings.
Inspect its diff and obtain rollout approval before creating it. Do not delete the original Job
or change its schema/data as a shortcut; preserve its evidence.

A follow-up pass re-enumerates Sessions and copies suffixes after committed service checkpoints.
It validates boundaries but **does not verify the skipped interior**. Keep a fixed per-Session
`through` manifest for verification. Writes beyond those watermarks can continue. Do not run an
unbounded rerun loop hoping to observe two moving databases at equality.

## 3. Verify exact bounded ranges

`verify_bin` is an operator-run tool, not an image startup task. Build/run from an authorized
workstation with database reachability. Inject connection URLs through the existing approved secret
mechanism into `AGENTPLANE_HISTORY_VERIFY_DATABASE_URL` (service DB) and
`AGENTPLANE_HISTORY_VERIFY_APP_DATABASE_URL` (app DB). Do not put passwords in CLI flags, output,
review comments or committed files. The tool opens read-only transactions, checks primary status,
and applies 10-second statement / 2-second lock timeouts. It never advances ingestion checkpoints.

For each public Session UUID and its recorded watermark:

```bash
bb run //agentplane/sandbox_service/session_history:verify_bin -- \
  --mode archive --session-id "$SESSION_ID" --through "$THROUGH" \
  --after 0 --batch-size 128 --max-batches 100 --timeout-s 60
```

The verifier compares **every** Event in the selected range: parse app proto-JSON, parse service
protobuf bytes, check cursor/origin/source consistency, and compare deterministic protobuf
serialization. This verifies the canonical data the app retained, not unknown wire fields already
lost before app storage. Events beyond `through` do not affect the check.

Each completed batch emits a JSON evidence record with the interval `(verified_after,
verified_through]`, fixed requested watermark, source identity and stored locator. Exit 3 means the
bounded invocation succeeded on only part of the requested range; rerun explicitly with `--after`
set to the last successfully reported cursor. A timeout/failure may also leave completed batch
records, but is not a completed verification. Retain the records and investigate the failure before
resuming. No automatic retries or on-disk mutable checkpoint are hidden in this tool.

A full verified prefix requires contiguous successful records from zero to the watermark, with the
same source identity and locator. A successful suffix alone is not full parity. Historical prefixes
must remain immutable while verification spans transactions/invocations; if either source is edited
or replaced, invalidate the evidence and restart verification. Empty history can pass archive parity
but cannot establish a runner binding. Reconcile missing/new Sessions separately from these ranges.

## 4. Verify a legacy live runner without changing its binding

First use Kubernetes provisioning evidence, not name matching, to identify the candidate incarnation.
Set `NAMESPACE`, `SANDBOX`, and independently reviewed `EXPECTED_UID`. Save before/after snapshots:

```bash
kubectl get sandboxes.agents.x-k8s.io "$SANDBOX" -n "$NAMESPACE" -o json > sandbox-before.json
jq -e --arg uid "$EXPECTED_UID" \
  '.metadata.uid == $uid and .metadata.deletionTimestamp == null' sandbox-before.json
POD="$(jq -r '.metadata.annotations["agents.x-k8s.io/pod-name"] // .metadata.name' sandbox-before.json)"
kubectl get pod "$POD" -n "$NAMESPACE" -o json > pod-before.json
jq -e --arg uid "$EXPECTED_UID" \
  'any(.metadata.ownerReferences[]?; .kind == "Sandbox" and .uid == $uid)' pod-before.json
kubectl port-forward -n "$NAMESPACE" "pod/$POD" 17000:7000
```

Stop on failed checks. Leave that port-forward running in its terminal. Use a local, explicitly
approved forward to the pinned Pod, not an arbitrary runner address. In a second terminal run:

```bash
bb run //agentplane/sandbox_service/session_history:verify_bin -- \
  --mode runner --session-id "$SESSION_ID" --through "$VERIFIED_ARCHIVE_THROUGH" \
  --runner-target 127.0.0.1:17000 --after 0 --max-batches 100 --timeout-s 60
```

Runner mode discovers the stored runner Session first and refuses to attach if absent. It supplies
no spec, setup script or Command; it only replays an existing Session and closes the attachment.
It compares bounded ranges of the runner spool against the archive, including source identity and
all overlapping Event bytes. Continue explicitly as above to cover the nonempty verified prefix.
Re-read the Sandbox and Pod after checks: UIDs must be unchanged, ownership must still match, and
neither object may be deleting. Record the Pod UID as well as the Sandbox UID. An interrupted
port-forward or changed identity invalidates association evidence; do not reconnect by name blindly.

**Runner mode proves only overlap at the supplied endpoint.** It cannot authenticate the endpoint's
Kubernetes association itself. The independently checked provisioning/port-forward evidence and
full overlap together support operator review; neither grants permission to update the UID. A
sampled first/last match, empty log or matching runner Session name is insufficient. If accepted,
prepare a separate narrowly scoped binding update conditioned on the unchanged public Session,
runner locator, source identity and currently NULL UID. Never bulk-fill NULL UIDs by name.

## 5. Continuous ingestion and ownership handoff

After verified import and reviewed binding readiness, enable shadow ingestion through its reviewed
rollout. Leave app ingestion active. Verify that each intended live Session is discovered and advances;
NULL UIDs, missing runner Sessions, suspended/deleting Sandboxes and unavailable spools are explicit
exceptions, not silent completion. Finish app-only historical suffixes separately.

For each handoff cohort:

1. Capture a fixed app watermark and verify service coverage/parity through it while writes continue.
2. Prepare the app projection/read path to consume the service's committed prefix. Current opt-in
   raw reads fail closed when the service lags the app cursor; a one-time equality check is not a
   safe read-switch protocol while independent ingesters race. **This consumer coordination is a
   remaining implementation gate, not something the verifier implements.**
3. Under a separately approved procedure, fence the old app ingester and record its final committed
   cursor. Wait for service coverage and verify any remaining suffix. Stop the old consumer, not
   the runner; retain runner spools and keep the service ingester running throughout.
4. Switch the prepared app readers/projections to service-owned history. Check replay/resume,
   authorization, projection lag and historical reads before retiring any old data or Jobs.

Do not switch if retained runner Events cannot bridge the final boundary. No period with both
consumers deliberately disabled, global quiet period, automatic startup, or runner storage deletion.
Rollback before handoff leaves app authority unchanged. After handoff, reverting to old app tables
requires copying/reconciling new authoritative history first; never silently serve a stale fallback.
Existing archive-ownership and cleanup gates remain. This runbook/tool PR deploys nothing.
