# Standalone subscriptions and notifications service

Status: **design decisions and implementation plan, not a shipped service.** This refines `ING`
(the Event & Notification Hub) in [the task DAG](task_dag.md#ing--event--notification-hub).
The first implementation follows Actions; GitHub and automatic lifecycle integration come later.
Endpoint/tool names below illustrate the intended operations, not an existing wire API.

**Scope revision:** runner sessions, not integration-app Threads, own the destination scope under the
authenticated ServiceAccount. The [shared runner discovery plan](runner_discovery.md) uses existing Kubernetes inventory,
not app Thread lookup, runner callbacks, or a separate directory service. V1 reuses network-policy
runner access; proper runner authentication/transport security is an explicit deferred TODO.

## Decisions

- **A separate, loosely coupled Agentplane service**, not a component of the integration app.
  It owns subscriptions, inboxes, and notification delivery bookkeeping. The app may be a client
  and provide a UI, but its process and private database tables are not the service interface.
- **ServiceAccount-authorized, runner-session-scoped resources.** Workloads under the same SA have
  the same authority, as with Actions/egress. Do not replace SA authority with sandbox or app Thread
  ownership checks. No per-session caller credentials or sibling-session isolation are required.
- **Explicit destination IDs everywhere in v1.** Supply them in agent context; never infer "current
  session". The proposed shape is a bound runtime reference plus `session_id`, under the authenticated SA.
  A bare session ID requires an additional SA-wide uniqueness contract that does not exist today.
- **Shared runner discovery, no directory service.** Extract the small Kubernetes-backed lookup
  library from the app for both consumers. Runners do not register with or call notifications.
- **Include service instructions in the agent prompt.** Explain how to subscribe/listen, retrieve,
  and explicitly acknowledge notifications, with concrete examples and the destination IDs.
- **Provider-owned semantics.** Each notification provider defines its payloads, filter schema,
  upstream authentication/verification, and source integration. Prefer upstream event names and
  fields rather than an Agentplane-specific vocabulary for the same facts.
- **Push an inbox notice; pull the content.** Deliver a small automated user-message input through
  the existing runner protocol. Do not inject every provider payload into the conversation.
- **Store the actual notification payload in every inbox entry.** Source references supplement the
  retained content; they do not replace it. Reading the inbox does not fetch content from the source.
- **Non-destructive reads, explicit acknowledgement high-water mark (HWM), no repeated reminders.**
  Runner confirmation, fetching content, and acknowledging it are distinct operations.
- **Running destinations only in v1.** No notification-triggered harness resume or sandbox startup.
- **Reuse network-policy runner access for v1.** Trust notifications as another control-plane client,
  tighten ingress/egress, and keep the RPC protocol unchanged. Proper runner authentication and transport
  security are a follow-up TODO; no command-level RBAC or receipt-only event stream is required.
- **One provider for v1: Actions.** Explicit subscriptions initially; automatic Action following is
  desirable later, but its exact submission/convenience interface remains undecided.

## Responsibilities and boundaries

The provider consumes a source, validates incoming events, defines notification content and filters,
and enforces source access through an authorized integration. Webhook signature verification is a
provider responsibility, not hard-coded GitHub logic in the generic service. A later GitHub provider
should retain names such as event `pull_request_review` and payload `action: "submitted"`; webhook
subscriptions and GitHub's Notifications API must not be conflated.

The service core manages subscription ownership/lifecycle, matching, deduplication, inbox cursors,
batching/debounce, quotas, retention, and delivery state. Keep the shared envelope limited to routing
and bookkeeping: stable identity, provider/type, source reference, matching subscriptions, and relevant
cursors/timestamps. The provider owns the content schema and rendering. Do not design a universal
notification payload before there is a second provider.

A delivery component inside the service attaches to the destination runner, submits an inbox notice,
and follows its receipts. This is not another Action executor, Decision authority, sandbox lifecycle
manager, or generic runner-command queue. The existing runner owns native command scheduling.

The Action Service remains the authority for Decisions and execution outcomes. Consume its canonical
ordered events; do not introduce a second Action outbox or authoritative Action event store. Every inbox
entry stores the provider-defined notification payload along with source references and service-owned
matching/delivery metadata. The retained payload is a notification snapshot, not a new source of
Action truth. Providers construct authorized/redacted content before persistence; retaining the
notification does not mean blindly copying credentials or an entire upstream response. Preserve individual source
events even when one notice covers a batch. Approval is not execution success; an unknown execution
outcome must never cause the notification service to resubmit the Action.

## Ownership and authorization

Use the shared [workload authentication](../docs/workload_authentication.md) foundation. Derive the
owner ServiceAccount from the authenticated principal, never from a caller-supplied `owner` field.
Every request names its runner session explicitly. Workloads under that same account can manage its
subscriptions and read/ack its session inboxes; another account cannot merely by knowing the IDs.
Verify resource ownership on operations by subscription ID as well.

The proposed qualified destination is `(destination_ref, session_id)`, scoped under that SA. Obtain
the trusted runtime ServiceAccount association and current runner endpoint through the
[shared discovery library](runner_discovery.md#proposed-library-seam). Validate the association before
binding a subscription; validate that the session exists without implicitly creating it. This does
not make sandbox membership the authorization principal or require app Thread lookup. Deriving a
self-delivery route from the authenticated Pod's provisioning association is routing, not Thread inference.
Session IDs alone are runner-local; do not silently assume account-wide uniqueness or choose the first
matching runner. Finalize the qualification contract before implementing storage keys.

Record the authenticated creator separately from the owning account/session. Destination access does
not grant source access: the Action provider also needs an authorized way to read the selected request.
Current Action caller-own access is ServiceAccount-based, so do not assume that the subscriptions
service's own workload identity can read another caller's requests. Choose a trusted delegation or
source-access mechanism before wiring this integration; do not solve it with unrestricted operator
reads. Recheck access as source authority or runner bindings are revoked or retired.

Cross-account delivery is out of scope for v1 and needs an explicit policy. Product Thread ownership
and an app Thread-to-session mapping are not prerequisites for notification ownership or routing.

### Service-to-runner access in v1

Use shared Kubernetes-backed discovery, then connect directly with the existing runner client. The
app-to-runner RPC path currently has no bearer authentication or TLS; Cilium ingress/egress policies
control network access. Reuse that model for notifications, permit its runner egress, and narrow runner
ingress to intended control-plane identities and audited test/administrative clients. Audit overlapping
rules and test denial for ordinary sandbox and unrelated same-namespace workloads.

Trust the service with the configured runner set's full protocol/history. It enforces agent-facing SA
ownership and destination bindings; the runner does not verify a per-session ticket. Not interrupting,
changing models, or resuming stopped harnesses is service behavior, not a new RPC permission system.

**TODO, after v1:** proper runner authentication and transport security for both app and notifications,
including trust provisioning, peer verification, rotation/revocation, and long-lived streams. See the
[explicit follow-up](runner_discovery.md#todo-proper-runner-authentication-and-transport-security).
Do not make a JWT issuer, app-issued Thread tickets, per-command RBAC, or a directory service a v1 gate.

## Proposed storage: service-owned PostgreSQL

Use PostgreSQL with a database and role owned by this service; sharing the existing PostgreSQL
infrastructure is fine, sharing the app's private tables is not. Access Action history through the
Action Service contract, not direct SQL against its database. This is the proposed implementation
approach; exact schema, retention limits, and worker-claim mechanics remain to be settled.

Persist these logical records:

- **Subscriptions:** owning ServiceAccount and qualified runner session, provider configuration,
  authenticated creator, creation idempotency key, lifecycle state, and source checkpoint.
- **Inbox entries:** ordered session-inbox-local cursor, stable provider event identity, source reference,
  matching subscriptions, and the actual provider-defined notification payload, always persisted.
  Reads serve that snapshot without refetching content from the source. Action lifecycle authority
  remains in the Action Service; retained notification content is not a second authoritative Action log.
- **Session inbox state:** cursor allocation, explicit acknowledgement HWM, and confirmed notice
  coverage. These last two positions must not be conflated.
- **Notice deliveries:** exact text, covered range, destination binding, stable runner command ID,
  and observed admission/confirmation/failure. Include enough identity to resume after a worker crash.
- **Runner-follow checkpoints:** last durably processed cursor, scoped to the runner event log, not
  confused with inbox or provider cursors.

The storage invariants matter more than the eventual table names:

1. Commit matched inbox entries, including their payloads, and advancement of their source checkpoint
   together. A crash may
   cause a reread but must not skip an event or duplicate an entry. Deduplicate stable source event
   identities within the destination inbox; record overlapping subscription matches separately.
2. Inbox cursors must describe a committed prefix. A plain PostgreSQL sequence is insufficient:
   transaction B could commit cursor 12 before A commits 11, letting acknowledgement skip a late
   entry. Serialize allocation/insertion with a short per-inbox row lock (or an equivalent
   proven scheme), releasing it at commit. Do not hold it during network calls.
3. Persist a notice's identity, exact input, and covered range before runner submission. Perform
   runner I/O outside database transactions; commit observed receipts and follow-checkpoint advancement
   consistently afterward. Reconcile uncertain sends with the existing runner journal.
4. Advance acknowledgement monotonically in an explicit transaction. Reads and notice receipts do
   not acknowledge. Expiry must expose a retention gap, not silently move the agent's HWM.
5. Coordinate concurrent workers through PostgreSQL with bounded claims/leases and idempotent
   processing. A recovered delivery keeps its command identity. Choose claim/recovery mechanics
   against actual worker concurrency; do not promise exactly-once native execution.

`LISTEN/NOTIFY` may wake workers after committed changes, but durable queries/reconciliation remain
the recovery path if a notification is lost. Keep retention and cleanup bounded, including terminal
subscription/delivery metadata and unacknowledged inbox entries, while preserving deduplication and
pending-recovery requirements. No Redis, Kafka, or separate message broker is needed for v1.

## Agent-facing operations

Expose provider/filter discovery and subscription create/list/get/update/cancel, plus inbox read and
acknowledge. Mutations must be safe to retry: use an idempotent subscription creation key and explicit
update concurrency semantics. Report subscription health, source cursor/availability, and delivery
failures separately; a recorded subscription is not proof of an active source watch or delivered notice.

Illustrative creation:

```json
{
  "destination_ref": {
    "namespace": "agentplane-staging",
    "name": "sandbox-example",
    "uid": "e03c0724-03c2-4d97-a45c-47fdc87eeb16"
  },
  "session_id": "session-123",
  "client_key": "follow-action-456",
  "provider": "actions",
  "config": {
    "request_id": "action-456",
    "after_sequence": 0
  }
}
```

Read and acknowledge are separate operations:

- `read(destination_ref, session_id, after_cursor, limit)` returns an ordered, bounded page without changing the HWM.
- `acknowledge(destination_ref, session_id, through_cursor)` monotonically advances the HWM. Repetition is harmless;
  an older cursor cannot move it backwards. Reject cursors beyond the inbox's committed position.
- Acknowledging `X` means **all entries through `X`**, not just entry `X`. Use service-assigned,
  session-inbox-local cursors, distinct from source event IDs and Action sequence numbers. Start with
  contiguous, unfiltered reads so paging does not encourage acknowledging unseen filtered entries.
- Acknowledgement is the agent's declaration that entries are handled, not evidence of successful
  external work. It need not immediately delete the retained entries.

### Agent prompt instructions

Ship prompt guidance with the first usable service, not only operator documentation or tool schemas.
Provide the agent's explicit runtime/session identifiers, the actual service endpoint/tool names and authentication usage,
how to discover accessible providers and their filters, and how to create/inspect/update/cancel its
subscriptions under its authenticated ServiceAccount. Describe inbox notices as automated wakeups to retrieve content, not the payload itself.
Instructions must explain that reads are non-destructive, acknowledgement advances a prefix HWM,
there are no repeated reminders, and v1 does not wake stopped destinations.

Include at least these two worked examples using the implemented API rather than leaving the agent to
invent call shapes:

1. **Listen for an Action:** submit an Action and obtain its real request ID, then create an idempotent
   subscription with the supplied `destination_ref` and `session_id`, that request ID, and replay from sequence zero. Explain
   that approval/completion before subscription creation is recovered from history, but creation must
   actually succeed. Continue other work and retrieve the inbox when its automated notice arrives.
2. **Read and explicitly acknowledge:** read a page after the current acknowledged cursor, inspect/handle
   its entries, and only then acknowledge through that page's last handled contiguous cursor. For
   example, starting from HWM 180, a read returning entries 181–184 does not change HWM 180;
   `acknowledge(destination_ref, session_id, through_cursor=184)` advances it after all four are handled. If only 181–182
   are handled, acknowledge through 182, not 184. Repeat pagination for any remaining entries.

Example IDs/cursors must be clearly distinguished from the real destination IDs and tool results. Do not
include real service credentials or imply that prompt text grants source/destination access. Explain
how to inspect a failed subscription or delivery rather than assuming silence means nothing happened.

Integrate guidance with the existing prompt/context composition; do not assume session standing
instructions can be changed in place. The [runner session contract](../runner/SPEC.md#sessions) fixes
`SessionSpec.instructions` for a session's lifetime. Supply guidance when creating enabled sessions;
if existing sessions are supported, choose an explicit supported context/input path rather than
silently changing the stored spec. Future runner-hosted MCP context can hide repetitive destination IDs
in tool calls, but does not replace the need to teach the agent the subscription and HWM semantics.

### Race-free explicit Action following

The planned default is to replay an Action from its beginning; `after_sequence` selects an already
consumed source prefix when supplied. A terminal Action is a valid subscription target. Thus an Action
that is approved and completed between submission and subscription creation still yields its Decision
and execution outcome. There is no need to make submission and subscription one distributed transaction.

Persist the source cursor and matched inbox entries consistently. Read canonical events after the
cursor, catch up, and use source notifications as wakeups to read again, not as the event history itself.
The catch-up/live handoff must not lose events; replay and reconnect must not duplicate inbox entries.
Define subscription update/cancellation boundaries against in-flight matching and replay.

This fixes an event race, not a missing-subscription failure: if the agent never completes the explicit
subscribe call, no subscription is guaranteed. A later submit-and-follow helper can simplify the calls
but cannot make two client requests atomic. A server-side convenience flag or automatic follow would
need durable authorized destination intent and idempotent reconciliation, not a best-effort second
HTTP request hidden inside Action submission. Its exact API and intent storage are deferred.

## Inbox notices and runner receipts

Send a bounded service-authored notice, for example:

> Agentplane notifications: 7 notifications are available through inbox cursor 184 for the bound runtime,
> session session-123. Retrieve them using the inbox read tool. This is an automated notification.

The count is a snapshot bounded by the cursor. Provider content is retrieved separately, retaining its
source provenance; external content is not promoted to operator instructions. Although the transport
is a user-message input, the notice is not represented as a human-authored message or runner observation.

Use the existing [runner protocol](../runner/SPEC.md#commands-and-effects):

1. Open an independent `Attach` stream for the existing session and follow from the last recorded
   cursor. Multiple attachments are supported; the integration app's attachment is not required.
2. Submit a `Command` with a stable `command_id` and `SubmitInput.text` containing the notice.
   Persist the command identity, exact text, and covered inbox boundary before attempting delivery.
3. `CommandAdmitted` means durable runner admission, **not** harness delivery.
4. `HarnessUserMessageConfirmed` is the causal delivery receipt. Match membership in
   `origin_command_ids`: Claude can coalesce multiple commands into one confirmation. Handle
   `CommandFailed`/`CommandNoop` without marking the notice confirmed.
5. Reconnect with `Open.follow.after_cursor` and reconcile durable receipts. Reuse the exact command
   and ID when retrying; do not create a fresh notice just because the response was lost.

Input can be submitted while the harness is idle or a turn is active. `SubmitInput` joins running work;
there is no common "next safe boundary"/steer mode to select. The adapters own native timing. The
[turn tests](../runner/test_turns.py) cover Codex joining an active turn and Claude inputs entering a
tool-result continuation with a coalesced confirmation. See also [attachment tests](../runner/test_attach.py)
and the [common protocol](../docs/common_protocol.md).

Confirmation does not prove that the agent fetched or handled notifications, nor does it promise
native persistence through every crash. Runner command deduplication is not an exactly-once guarantee
across native execution before durable outcome evidence. Preserve this evidence boundary in status
and recovery; do not infer receipt from a socket write, turn completion, or lack of an error.

### No repeated reminders

Track notice coverage independently from the agent's acknowledgement HWM. Batch/debounce new arrivals,
with bounded notices and fair delivery across destinations. Arrivals beyond an in-flight notice's
covered cursor remain eligible for a later notice; they must not be lost when the earlier receipt arrives.

Once a notice is harness-confirmed, unacknowledged entries alone never trigger another notice. New
arrivals can trigger a notice for the newly uncovered range, not a reannouncement of the old backlog.
Retries of an unconfirmed command are transport recovery, using the same identity, not reminders.
A harness restart is not a reason to repeat a confirmed notice. Bound retries/backoff and surface failures
rather than turning persistent failure into an input storm. If entries are acknowledged before a notice
is submitted, suppress unnecessary notices; an already-admitted command cannot be assumed withdrawn.

## Lifetime and unavailable destinations

Subscriptions belong to the authenticated SA and qualified runner session, not an app Thread,
attachment, or harness process. Temporary disconnect, process restart retaining state, or runtime
suspension does not itself cancel them. Explicit cancellation stops future matching but does not
acknowledge existing inbox entries or cancel the Action. Already-submitted notices may still arrive;
cancellation is not selective runner-input withdrawal. App Thread archiving has no implicit effect;
any future archive-to-subscription behavior must be explicit integration.

V1 delivers only to a running harness. `Open` without a spec observes an existing session without
starting it; a stopped session replays and ends. Starting/resuming requires an explicit spec, which the
notification service must not supply to wake a stopped destination in v1. Failed/running setup and
harness launch are not successful delivery. A stop racing with submission still needs honest receipt
reconciliation, not an offline-delivery claim.

Use authoritative runtime removal from the shared inventory, or an explicit session-retirement
operation, for permanent-destination cleanup. Missing
endpoints, timeouts, failed lookups, or absence from a list are not retirement. Finalize session-retirement
and orphan-retention rules before implementation; the runner's current API has no general session-delete
operation to assume. Never silently retarget a replacement runner or a reused session ID.
Keep accepted inbox entries and their payloads under bounded retention, making expiry/replay gaps visible rather than
silently acknowledging them. They remain readable when the agent returns. A coalesced notice on the
next running harness is desirable but **not a v1 acceptance requirement**; initially there is no
complete offline/catch-up delivery promise. Retaining accepted notifications and recovering events
never received from an upstream are different guarantees. Stop/reconnect handling must not lose an
already-recorded receipt or reinterpret it as an acknowledgement.

## Implementation sequence and remaining choices

1. **Extract shared runner discovery:** reuse existing Kubernetes inventory through a small library
   used by the app and notifications, not a new directory service. Settle retained-runtime identity,
   SA associations, endpoint/removal semantics, and explicit session qualification. Reuse and tighten
   network-policy access; proper RPC auth is deferred. Separately settle authorized Action reads.
2. **Build the standalone service:** owned persistence/migrations, provider discovery, explicit
   SA-authorized session-scoped subscription CRUD, inbox cursor/read/HWM operations, and observable health/errors.
   Pick concrete limits, retention, idempotency/update contracts, and cancellation race semantics.
   Wire agent prompt instructions with the actual runtime/session identifiers, service usage, and subscribe/read/ack examples.
3. **Implement only the Action provider:** canonical replay and follow, source authorization,
   individual ordered Decisions/outcomes, and atomic cursor/matching bookkeeping.
4. **Deliver notices through the runner:** independent attachment, persisted command identity and
   coverage, debounce/backpressure, receipt replay, and no reminders or automatic startup.
5. **Prove the full slice:** scripted runner tests plus a deployed agent submits an Action,
   subscribes, receives the notice, reads the inbox, and explicitly advances its HWM.

This document proposes service-owned PostgreSQL but does not select an HTTP/MCP wire surface, JWT
issuer, exact database schema, or numeric quotas.
Resolve those against the existing service/auth patterns rather than treating illustrative names here
as a shipped API. Operator UI and generic webhook setup are not prerequisites for the first slice.

## Later, not v1

- **GitHub and other providers:** provider-owned verification, connection setup, payloads, filters, and
  familiar upstream vocabulary. Use a real second provider to refine the abstraction.
- **Automatic Action subscriptions / a convenience submission option:** desirable, with durable intent
  and replay; exact UX and integration remain open.
- **Resume delivery and notification-triggered wake:** first deliver a coalesced outstanding notice
  when a harness returns; later request authorized harness/sandbox resume through the lifecycle owner.
  Wake policy and budgets are separate from notification delivery. No automatic resume in v1.
- **Runner-hosted MCP conveniences:** a connection bound to a runner session could reliably supply
  `destination_ref`/`session_id` for "my inbox" tools. Hosting an undifferentiated sandbox-wide MCP endpoint is not enough.
  Keep the service API explicit; this provides context, not sibling-session isolation.
- **Cross-account delivery and product Thread integration:** separate authorization/lifecycle decisions,
  including archive behavior or following a Thread across successor runner sessions. No implicit retargeting.
- **Proper runner authentication/transport security:** the explicit TODO in the shared discovery plan;
  implement consistently for app and notifications, not as a v1 prerequisite.
- **Discovery extensions:** a separate directory API or external-runner registration needs a concrete
  consumer. Neither is required for hosted v1 or a reason for runners to call notifications.

## Acceptance criteria

- Workloads sharing an SA can access its session-scoped resources; a caller under another account
  cannot. Forged owner IDs, mismatched runner bindings, and unauthorized Action sources fail closed.
  The service never resolves a workload into an app Thread or accepts arbitrary destination URLs.
- Enabled agent sessions receive service instructions and the correct explicit runtime/session identifiers in their
  prompt/context, with working subscribe and read/ack examples using the shipped API. Verify the agent
  can follow them without relying on undocumented tools or implicit session detection.
- Retried subscription creation produces one subscription. A decision and completion before creation
  are replayed, including for terminal Actions. Catch-up/live races and source replay lose no events
  and create no duplicate entries. Approval never stands in for execution success.
- Concurrent inbox insertion cannot expose a later cursor before an earlier transaction commits.
  Crashes around source-checkpoint commits and notice submission do not skip entries or create new
  command identities; worker recovery uses durable state rather than relying on `NOTIFY`.
- Every retained inbox entry has its actual notification payload. Reading it does not refetch source
  content; provider unavailability or later source changes do not replace the stored snapshot. Inbox
  access remains authorized, and expiry remains explicit.
- Reads do not acknowledge. HWM advancement is monotonic/idempotent, applies to a contiguous prefix,
  and rejects a future cursor. Retention gaps are visible. Subscription cancellation does not cancel
  an Action or erase/ack its existing inbox entries.
- Idle and busy Claude/Codex harnesses receive notices with correlated confirmation; coalesced origin
  IDs are handled correctly. Admission is not reported as delivery. Reconnect and response loss reuse
  the same command and recover observed receipts without claiming stronger native crash guarantees.
- New arrivals during an in-flight notice receive later coverage. An unread/unacknowledged confirmed
  notice is not repeated, including after reconnect/restart. Bursts and delivery failures stay bounded.
- A stopped harness is not resumed; temporary absence preserves subscriptions and retained inbox
  entries. Permanent deletion cleans up via authoritative state, without retargeting another runner/session.
- The independently deployed service works using the shared discovery library, without the integration app's
  process, Thread API, delivery attachment, or private database tables. App and notifications have
  runner network access; ordinary sandbox and unrelated same-namespace workloads do not. No new
  RPC credentials or command-level RBAC are required. Source availability, pending/failed delivery,
  and acknowledgement remain distinct.
