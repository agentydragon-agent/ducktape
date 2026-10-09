# Notification presentation and input metadata

Status: proposed; implementation blocked on the in-flight Session Event archive ownership cutover. The [task DAG](task_dag.md#notification_presentation--compact-notification-rendering)
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

| Field            | Proposed storage                | Content                                                    |
| ---------------- | ------------------------------- | ---------------------------------------------------------- |
| Session identity | Existing relational session key | Full session scope, not a globally assumed session string  |
| Command ID       | Existing command ID type        | Unique together with session identity                      |
| Text             | PostgreSQL text                 | Immutable accepted input                                   |
| Metadata         | Nullable JSONB                  | Typed, validated attachment with server-stamped provenance |
| Accepted time    | Timestamp with time zone        | Service acceptance time, not harness receipt time          |

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

The [Session Event archive migration](session_archive_placement.md) is already moving durable raw
history to Sandbox Service; its backfill/write/read handoff must finish before this persistence work.
Reuse the resulting session identity and database ownership. Input records are distinct from copied
execution Events: neither archive ownership nor input metadata implies offline command acceptance.
Resolve persistence-before-dispatch, caller retries and retention in `SESSION_INPUT_CONTRACT` before
implementation. Do not add automatic execution after reconnect or wake a destination.

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

The [DAG](task_dag.md#2-service-owned-inputs-and-notification-presentation) owns status and edges:

1. `SESSION_INPUT_CONTRACT`: review typed API, acceptance/dispatch semantics and storage against the
   migrated session model. This design can run during backfill; it must not add a parallel database.
2. `SESSION_INPUT_SUBMISSION`: after `THREAD_ARCHIVE_OWNERSHIP` and contract review, implement
   authorized, immutable submission persistence and translation to runner text-only commands.
3. `SESSION_INPUT_METADATA_READ` and `NOTIFICATION_NOTICE_METADATA`: independently implement
   authorized annotation reads/correlation and producer attachments after the submission API exists.
4. `NOTIFICATION_PRESENTATION`: integrate compact frontend rendering after both paths are available.

Tests cover ordinary input, restricted provenance, destination authorization, identical/conflicting
retries, crashes around dispatch, pending/failed inputs, replay and mixed-origin coalescing. Keep
metadata out of runner commands; keep historical annotations after inbox expiry. Exercise backend
integration without the app. Add frontend visual coverage and one bounded real-notice demonstration
with unchanged agent-facing text. No provider-outage injection or repeated harness matrix is needed;
rendering must not acknowledge the inbox.
