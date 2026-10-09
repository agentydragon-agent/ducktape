# Notification presentation and input metadata

Status: immediate-dispatch and spool-reconciliation direction selected; remaining contract details
need review. Implementation blocked on the in-flight Session Event archive ownership cutover. The [task DAG](task_dag.md#notification_presentation--compact-notification-rendering)
tracks the sequenced phases below. Contract design can proceed during backfill, but no new Sandbox
Service/app database work starts before that cutover. This plan replaces the earlier proposal to carry presentation metadata through
runner commands and journals.

## Goal and boundaries

Give user inputs typed metadata that is not passed to the runner or harness. Initially, identify
Notification Service notices so the frontend can render them compactly, with full text available
on expansion. The agent continues receiving the existing actionable notice text.

- Sandbox Service owns input submission, authenticated provenance and durable input metadata.
- Notification Service owns subscriptions, inboxes, entries and delivery bookkeeping.
- Runners remain responsible for execution and canonical admission/confirmation evidence. They
  neither receive nor interpret this metadata; Claude/Codex integrations do not change.
- The integration app consumes authorized service APIs and renders annotations. No backend
  depends on app tables, availability or identity.

This does not add native subsessions, change notice pacing, acknowledge inboxes through rendering,
introduce another service, or provide notification-triggered startup/wake.

## Submission API

Expose a Sandbox Service input-submission request rather than nesting a raw runner Command in the
public request. Illustrative JSON (not a choice of HTTP over the existing service transport):

```json
{
  "command_id": "...",
  "text": "Agentplane inbox notice: ...",
  "metadata": {
    "notification_notice": {
      "inbox_id": "...",
      "through_cursor": 123
    }
  }
}
```

The destination/session remains scoped by the service API. Metadata is a typed, bounded schema,
not an arbitrary dictionary. Plain human input needs no notification attachment. Define the exact
notice identity and cursor fields from the existing persisted delivery record; do not mint another
identity if the command ID already uniquely identifies that notice. A notice may cover multiple
sources. Start with stable inbox/range references; add only bounded source descriptors needed for
presentation, not full provider payloads or a single misleading source label for a batch.

Sandbox Service validates and persists the submission, then immediately constructs and sends the
existing runner Command from command ID and text only, within the same RPC. The service submission
and runner Command are distinct types/records: use an explicit allowlisted conversion, not a shared
metadata-bearing object forwarded to the runner. The RPC returns OK only with runner admission,
not merely because the service persisted the submission. Other runner operations need not be
redesigned for this feature.

## Trusted provenance

Use the existing authenticated caller and destination authorization. Attaching notification metadata
requires an additional narrowly scoped permission granted only to the Notification Service workload
identity. Confirm the actual service authentication/policy integration before choosing the permission
representation; a claimed service name in a header or request body is not authentication.

Unauthorized metadata receives a permission-denied response before persistence or dispatch, not
silent stripping. Notification Service must still be authorized to submit to the target session.
Sandbox Service stamps trusted notification provenance after authorization; callers supply notice
references, not their own trusted producer identity. No new signatures or callback validation service
is required. Notification Service remains responsible for reference correctness.

Provenance means the service submitted this notice, not that provider text is trusted. Never infer
provenance from text prefixes. Metadata is excluded from model input, but is not thereby secret:
read APIs must enforce session access and return only authorized fields.

## Current command path: no app-backend queue to retire

Source inspection at `c38998b5` found a browser outbox, not an app database command queue:

- The composer creates a command ID and `LocalCommands.remember()` persists the full immutable
  command in browser `localStorage` before HTTP or clearing the composer. Unadmitted commands can
  be retried on mount, connectivity recovery or explicit retry, with the same ID and contents.
- The app command endpoint checks archived admission evidence, then relays through Sandbox Service.
  `ThreadContent.admitted_command()` explicitly implements an archive lookup, not an outbox.
- Sandbox Service's `admit_running_command()` attaches to an existing running session and waits for
  the exact runner admission receipt. It does not enqueue offline work or start a stopped harness.
- The runner journals admission before scheduling native work; its durable commands and execution
  scheduling are a separate responsibility that this plan does not replace.

See [browser recovery](../app/frontend/threads/local_commands.ts),
[submission/retry](../app/frontend/threads/thread_commands.tsx),
[app relay](../app/threads/bridge.py), [archive lookup](../app/threads/view/content.py),
[service relay](../sandbox_service/command_relay.py) and [runner journal](../runner/journal.py).
These are source findings, not proof of the deployed version. Do not add an app queue drain or
retirement phase based on the earlier assumption that such a backend queue existed. Keep browser
recovery for requests that never reached the service; reconcile its handoff with service receipts.

## Persistence, immediate dispatch and reconciliation

Sandbox Service owns a durable submission record containing scoped Session identity, command ID,
immutable text, typed metadata, authenticated provenance, acceptance time and admission status/evidence.
Inspect existing service storage before choosing the concrete schema; reuse suitable owning records
without conflating the service submission with the runner's stripped-down Command. Do not introduce
an independent metadata database. Inbox/source references are identifiers, not cross-service foreign
keys. Subscription cancellation or inbox expiration must not erase retained input annotations. Keep metadata as an immutable accepted snapshot rather than deriving
historical annotations from mutable subscription state.

### One submission RPC

1. Authenticate and authorize destination and metadata before persistence or dispatch.
2. Atomically persist command and metadata as `pending_admission`.
3. Immediately attempt dispatch of the runner Command, with the same command ID, in this RPC.
4. On a matching durable `CommandAdmitted` receipt, record `admitted` and return OK with the receipt.
5. On a definitive refusal proving non-admission, record `rejected` and return an error.
6. On timeout, transport loss, cancellation or crash, leave `pending_admission`; an error must not
   claim rejection when admission may already have happened.

`pending_admission` means the service retained the submission but has not recorded a definitive
admission outcome. It combines not-yet-sent and possibly-sent cases; no separate persisted `unsent`
or `dispatching` lifecycle state is needed. It does not prove that cancellation is safe or promise
background delivery. Attempt/error diagnostics may be retained separately. Runner admission is not
harness confirmation or execution success.

### Immutable retries and spool evidence

Session identity plus command ID identifies a submission. Identical validated retries reuse it;
different command contents or metadata conflict, never overwrite. Authorization applies to retries.
An admitted retry returns the retained receipt. Pending retries reconcile admission evidence or
attempt the identical runner command using existing runner deduplication; never mint a replacement
ID to resolve uncertainty. Concurrent retries must converge on the same submission and receipt.

Use the planned service-owned runner spool/Event ingestion and replay to reconcile admission even
when the RPC reply is lost or the service restarts. Direct RPC receipts and ingested admissions are
two paths to the same durable fact and must converge idempotently. Catch-up must not advance past
reconciliation work in a way that strands a pending submission after a crash. Absence from a lagging
archive is not proof of runner rejection. Subsequent Events remain the evidence for harness effects.
No dedicated runner command-status RPC is required for this design.

Service-owned spool ingestion is part of the event-storage migration, not an asserted deployed
capability. Coordinate with its owner and verify ingestion/replay integration before claiming this
recovery guarantee; do not introduce a temporary dependency on app ingestion or app tables.

This is immediate dispatch with durable submission evidence, not a new background execution queue.
Do not add a retry worker, automatic dispatch merely on reconnect, or session startup/wake. Caller
retries and ingestion of outcomes from already-attempted commands are distinct from such behavior.

### Remaining contract review and migration gate

The [Session Event archive migration](session_archive_placement.md) must finish its ownership
handoff before new submission persistence work under the current DAG hold. This design does not
approve an exception. Reuse its Session identity and ingestion authority.

Before implementation, settle the concrete service schema/auth integration and notice fields,
submission retention/deletion, and retryable pre-admission failures versus terminal rejections
(including stopped sessions and conflicting command IDs). Preserve uncertainty where an earlier
attempt might have been admitted; a later failed attempt must not erase valid admission evidence.
The immediate-dispatch/single pending-state/spool-reconciliation direction above is selected, not
an open choice of offline queue or a second command authority.

## Correlation and read path

Existing runner evidence already supplies the necessary joins:

- Command admission identifies the submitted command.
- `HarnessUserMessageConfirmed.origin_command_ids` identifies originating commands for a confirmed
  harness message, alongside its harness message ID.

Sandbox Service exposes input metadata keyed by session/command identity through an authorized read
API. The message projection uses origin IDs to attach annotations, including pending or failed inputs
where no confirmed message exists yet. Preserve annotation availability across replay/reconnect and
client archival without rewriting canonical runner Events or requiring runners to echo metadata.
Select the exact read/projection integration after inspecting current archive ownership; an enriched
view is not a new canonical execution Event.

Coalesced inputs may mix human text and notices. Preserve metadata per originating command. Origin
IDs do not prove substring boundaries: do not collapse a whole mixed message or attempt to extract
human text using prefix heuristics. Initially render mixed messages normally with annotations.

## Frontend behavior

### Submission status TODO

Extend the command-state dots with **stored by Sandbox Service; runner admission unconfirmed**
between browser retention and runner admission. Drive this from authorized submission status reads
or a feed, including recovery after a lost RPC response; a waiting RPC alone does not expose the
intermediate state. Do not label it definitely unsent or guaranteed eventual delivery. Keep runner
admission distinct from harness confirmation. This status work is independent of compact notice
rendering and must not give the app dispatch ownership.

### Notification rendering

- Compact notification-only messages by default, with accessible expansion to full retained text.
- Use verified provenance, never text matching, to select notification presentation.
- Missing or unknown metadata falls back to ordinary text rendering.
- Provider titles/descriptions remain untrusted content and must be rendered safely.
- Keep mixed-origin messages readable; never hide human input.
- Rendering, expansion and reading metadata do not acknowledge an inbox.

## Implementation sequence and acceptance

The [DAG](task_dag.md#2-service-owned-inputs-and-notification-presentation) owns status and edges:

1. `SESSION_INPUT_CONTRACT`: review typed API, acceptance/dispatch semantics and storage against the
   migrated session model. This design can run during backfill; it must not add a parallel database.
2. `SESSION_INPUT_SUBMISSION`: after `THREAD_ARCHIVE_OWNERSHIP` and contract review, implement
   authorized, immutable submissions, immediate dispatch, and spool-based admission reconciliation.
3. `SESSION_INPUT_METADATA_READ` and `NOTIFICATION_NOTICE_METADATA`: independently implement
   authorized status/annotation reads and producer attachments after the submission API exists.
   `SESSION_INPUT_STATUS_UI` then adds the service-retained command-state dot independently of notice rendering.
4. `NOTIFICATION_PRESENTATION`: integrate compact frontend rendering after both paths are available.

Tests cover ordinary input, restricted provenance, destination authorization, identical/conflicting
retries (including concurrent requests), crashes around dispatch, pending/rejected inputs, replay
and mixed-origin coalescing. Cover admission before a lost reply, ingestion racing an RPC receipt,
and crash/replay at the reconciliation checkpoint; prove none strands or regresses admission state. Keep
metadata out of runner commands; keep historical annotations after inbox expiry. Exercise backend
integration without the app. Add frontend visual coverage and one bounded real-notice demonstration
with unchanged agent-facing text. No provider-outage injection or repeated harness matrix is needed;
rendering must not acknowledge the inbox.
