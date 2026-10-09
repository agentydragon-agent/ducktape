# Notification presentation and input metadata

Status: proposed; no implementation yet. The [task DAG](task_dag.md#notification_presentation--structured-metadata-and-compact-notification-rendering)
tracks this work. This plan replaces the earlier proposal to carry presentation metadata through
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

Sandbox Service validates and persists the submission, then constructs the existing runner Command
from command ID and text only. Other runner operations need not be redesigned for this feature.

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

## Persistence and idempotency

Store the attachment in Sandbox Service, not Notification Service. Session rendering must not need
cross-service database joins or live subscriptions/inboxes. Keep a stable snapshot of metadata as
accepted rather than deriving historical annotations from mutable subscription state.

First inspect the current durable submission model and coordinate with concurrent Sandbox Service
work. Reuse an existing accepted-input record if present. Otherwise propose a narrow submitted-input
record with:

| Field | Proposed storage | Content |
| --- | --- | --- |
| Session identity | Existing relational session key | Full session scope, not a globally assumed session string |
| Command ID | Existing command ID type | Unique together with session identity |
| Text | PostgreSQL text | Immutable accepted input |
| Metadata | Nullable JSONB | Typed, validated attachment with server-stamped provenance |
| Accepted time | Timestamp with time zone | Service acceptance time, not harness receipt time |

This is a conceptual schema, not authorization to duplicate existing input/text storage. Determine
foreign keys, concrete ID types, retention and deletion with the actual owning model. Prefer metadata
on the existing input row over an independent metadata store. Inbox/source references are identifiers,
not cross-service foreign keys; subscription cancellation or inbox retention must not remove the
annotation from a retained session input.

Persist the accepted input and metadata atomically before dispatch. Repeating a command ID with the
same validated submission is idempotent; different text or metadata must conflict, not overwrite it.
Authorization applies to retries too. A database commit is not runner admission or execution success.
Crash recovery and ambiguous dispatch must use the same command ID and existing receipt reconciliation,
not create a second command or a second execution authority.

The [current Sandbox Service plan](sandbox_service.md#event-following-and-archive-ownership)
explicitly leaves execution-event archival to clients and does not promise offline command acceptance.
This proposal adds durable submission metadata, not an execution-event archive or background offline
command queue. Before implementation, reconcile the persist-before-dispatch flow with that contract:
state what happens when dispatch fails, how callers retry after crashes, and when retained submission
records can be deleted. Do not silently add automatic execution after reconnect or wake a destination.

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

- Compact notification-only messages by default, with accessible expansion to full retained text.
- Use verified provenance, never text matching, to select notification presentation.
- Missing or unknown metadata falls back to ordinary text rendering.
- Provider titles/descriptions remain untrusted content and must be rendered safely.
- Keep mixed-origin messages readable; never hide human input.
- Rendering, expansion and reading metadata do not acknowledge an inbox.

## Implementation sequence and acceptance

1. Resolve the persistence/dispatch boundary and typed API against current Sandbox Service code;
   update its owning plan for the chosen input-submission contract without changing archive ownership.
2. Implement authenticated metadata submission, immutable persistence and authorized reads. Test
   ordinary submissions, restricted provenance, destination checks, conflicting retries and crashes
   before/after dispatch. Prove metadata never appears in the runner command.
3. Have Notification Service attach metadata using its existing delivery command identity. Preserve
   retry and receipt reconciliation behavior; prove inbox deletion does not invalidate retained input
   annotations. Exercise this backend path with the integration app unavailable.
4. Integrate the projection and frontend. Test pending/failed inputs, confirmation joins, replay,
   reconnect, archived reads, batched sources, mixed-origin coalescing, missing/unknown metadata and
   notification-looking human text. Verify unauthorized readers cannot obtain annotations.
5. Verify a real notice renders compactly and expands to its full text while the agent receives
   unchanged actionable text. Include frontend visual coverage and confirm no rendering action
   acknowledges notifications.
