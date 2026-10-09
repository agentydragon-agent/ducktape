# Agentplane task DAG

This is the dispatch map for **unfinished** work. Detailed contracts belong in component plans;
completed work belongs in component docs, not done nodes here. Maintenance rules are in
[AGENTS.md](../AGENTS.md#task-dag-maintenance). Deliberately deferred candidates and conditional
hardening live in the [freezer](task_freezer.md), not the execution graph.

## Current state and scheduling

**In flight: Session Event history migration from the app to Sandbox Service.** The operator
reported a backfill log at `2026-10-09T01:28:42.837707193-07:00`: one session had
`stored=925696/3568560 new=925696 rate=234.8 Events/s`. This is partial progress for one session,
not a global completion estimate or a fresh observation by this documentation change. Coordinate
with the agent already owning the migration; do not launch a second backfill or competing cutover.

Source now contains service-owned history storage, resumable import, shadow ingestion and opt-in
app raw-history reads. Placement is no longer an open choice. Source is not proof that the live
write/read handoff is complete. See the [archive plan](session_archive_placement.md),
[import runbook](../sandbox_service/session_history/BACKFILL.md) and
[read handoff](session_history_read_cutover.md).

**Sequencing hold:** finish `THREAD_ARCHIVE_OWNERSHIP` before unrelated additions to the Sandbox
Service database or app database surgery. App raw-table removal and schema consolidation have
additional dependencies below. This is a start-work constraint, not just a gate on merging.
Migration-owned changes continue; API/policy design and independent UI work can proceed without
changing the migrating schema. Do not use a parallel command/metadata database to evade the hold.

**Next useful parallel work:** prepare the input-submission contract and operator-reviewable
multiagent/read-policy decisions. The previously requested scoped-read design remains useful now;
its implementation waits for the archive and trust-boundary decisions. No new multiagent transport,
native-subagent integration, offline command queue, or extra worker service is selected here.

States: **in flight** means reported work is underway; **decision** needs a reviewed outcome;
**blocked** names prerequisites; **candidate** is dispatchable when selected, not a priority claim.
A **capstone** closes an integrated contract, not another implementation. Solid arrows below are
prerequisites; dashed arrows explicitly label scheduling holds or conditional choices. All service
contracts remain multi-replica unless a reviewed temporary restriction says otherwise.

## 1. Finish the history migration before expanding persistence

```mermaid
flowchart TD
    THREAD_ARCHIVE_BACKFILL[In flight: import and verify existing prefixes]
    THREAD_ARCHIVE_INGEST[Blocked: shadow parity and live writer handoff]
    THREAD_ARCHIVE_READ_CUTOVER[Blocked: enable archive-backed raw reads]
    THREAD_ARCHIVE_UI_CUTOVER[Blocked: app consumes archive for folds and metadata]
    THREAD_ARCHIVE_OWNERSHIP[Capstone: service is sole durable raw archive]
    APP_RAW_HISTORY_RETIRE[Blocked: retire obsolete app raw tables and import tooling]
    THREAD_IDENTITY_NEW[Blocked: finish service-owned new Session identity cutover]
    THREAD_EVENT_CONTINUITY[Capstone: new and legacy identity continuity]
    APP_ALEMBIC_SQUASH[Blocked: baseline final app schema]
    SESSION_EVENT_RETENTION[Blocked: measure and select history retention]
    THREAD_ARCHIVE_BACKFILL --> THREAD_ARCHIVE_INGEST
    THREAD_ARCHIVE_INGEST --> THREAD_ARCHIVE_READ_CUTOVER
    THREAD_ARCHIVE_READ_CUTOVER --> THREAD_ARCHIVE_UI_CUTOVER
    THREAD_ARCHIVE_UI_CUTOVER --> THREAD_ARCHIVE_OWNERSHIP
    THREAD_ARCHIVE_OWNERSHIP --> APP_RAW_HISTORY_RETIRE
    THREAD_ARCHIVE_OWNERSHIP -. migration hold .-> THREAD_IDENTITY_NEW
    THREAD_ARCHIVE_OWNERSHIP --> THREAD_EVENT_CONTINUITY
    THREAD_IDENTITY_NEW --> THREAD_EVENT_CONTINUITY
    APP_RAW_HISTORY_RETIRE --> APP_ALEMBIC_SQUASH
    THREAD_EVENT_CONTINUITY --> APP_ALEMBIC_SQUASH
    APP_RAW_HISTORY_RETIRE --> SESSION_EVENT_RETENTION
```

### `THREAD_ARCHIVE_BACKFILL` — one-way import and prefix verification

**In flight; existing migration owner.** Finish/resume import from committed cursors, including
legacy and deleted-Sandbox histories. Retain public UUIDs, native locators and existing Thread URLs.
The import's fast resume validates checkpoint boundaries, not every skipped Event: complete the
runbook's canonical-byte/prefix comparison and close live-writing gaps before handoff. Resolve
active legacy histories with unknown Sandbox UID using verified incarnation evidence, not name
matching. Completion is all scoped histories accounted for, not a Job being Running or one session
reaching its ceiling. Keep backups/high-water marks; do not rename native files or reset databases.

### `THREAD_ARCHIVE_INGEST` — shadow parity and writer handoff

**Blocked on backfill/identity verification for the affected logs.** Shadow-copy code exists; the
remaining outcome is a caught-up, fenced live ingestion path independent of app folds. Finish any
missing owner/claim behavior and reconcile final cursors while quiescing the old raw writer. Use
existing duplicate/conflict and replica/reconnect tests; a bounded handoff comparison covers the
actual migration. An incomplete source prefix or unresolved legacy locator is a real blocker.

### `THREAD_ARCHIVE_READ_CUTOVER` — enable service-backed raw reads

**Blocked on verified backfill and ingestion parity.** Deploy the service reader before enabling
the app's opt-in history switch. Check raw paging, stream resume, old native evidence and denial to
non-authorized service accounts. Lag must remain explicit, not fall back to stale app rows. This
read-only step does not establish sole write ownership or permit deleting app tables.

### `THREAD_ARCHIVE_UI_CUTOVER` — app becomes an archive consumer

**Blocked on raw-read handoff.** Move remaining app raw observation metadata reads and fold input
to archive replay with independent checkpoints. Stop app raw ingestion; keep app-owned UI folds
and operator metadata. Preserve raw progress when a projector fails and expose fold lag/error.
Remove direct SA transcript bypasses, not security checks. See the [read handoff plan](session_history_read_cutover.md).

### `THREAD_ARCHIVE_OWNERSHIP` — archive cutover capstone

**Blocked on all preceding migration phases.** One durable raw archive belongs to Sandbox Service;
app readers/projectors consume it without backend-to-app queries. Record final prefix parity,
writer ownership and a bounded read/reconnect check, including a retained deleted-Sandbox history.
Keep the runner journal as the source of execution facts. The migration owner records cutover and
rollback evidence in the archive plan/runbook. Only then release the persistence expansion hold.
This does not grant agent reads, make harness state portable, or move command admission.

### `APP_RAW_HISTORY_RETIRE` — remove obsolete storage

**Blocked on ownership handoff.** Inventory remaining references, preserve required identity and
fold associations, then remove old raw writes/tables and one-off import tooling when rollback no
longer needs them. Do not delete the durable legacy runner-locator mapping. This is a separate
finishable change, not something hidden inside enabling the read flag.

### `THREAD_IDENTITY_NEW` — service-owned identity for new histories

**Blocked by the migration scheduling hold.** Finish the
[app identity cutover](app_session_identity_cutover.md): use the service-reserved public UUID,
resolve cwd after reservation, and recover a committed Open via authorized lookup. Preserve
legacy private runner locators, native storage and existing URLs. This is not a new public-ID
placement decision. Coordinate any already-open implementation with the migration owner.

### `THREAD_EVENT_CONTINUITY` — identity cutover capstone

**Blocked on ownership and new-ID cutovers.** Verify the retained legacy association and the new
identity path through Open/resume/replay without inventing a second Event counter. Existing
same-storage runner restart/resume tests remain evidence; do not demand copied-volume portability
or a new native experiment. If this particular cutover changes a runner protocol/image, use a
compatible guarded rollout; automatic fleet upgrades are not inherently a prerequisite.

### `APP_ALEMBIC_SQUASH` — consolidate the final app schema

**Blocked on raw-table retirement and identity continuity.** Baseline only the settled schema,
verify fresh and migrated databases and their deployed stamps before pruning old revisions.
Retain the data-preserving rollback procedure. No Action Service or other database squash implied.

### `SESSION_EVENT_RETENTION` — measure before changing history retention

**Blocked on old-copy retirement.** Re-measure actual table/TOAST/index and fold/evidence costs;
the earlier app sample (~6.2 GiB raw Events, ~11m rows) is not the final service footprint. Present
a policy for redundant terminal text/tool deltas before implementing deletion. Keep incomplete
turns and raw/native evidence by default; final UI text is not proof a native frame is reconstructible.
Use replay/fold tests and bounded storage measurement, not an open-ended live failure exercise.

## 2. Service-owned inputs and notification presentation

```mermaid
flowchart LR
    SESSION_INPUT_CONTRACT[Decision: typed input API and durable acceptance contract]
    THREAD_ARCHIVE_OWNERSHIP[Archive ownership cutover]
    SESSION_INPUT_SUBMISSION[Blocked: input API, storage and provenance authorization]
    SESSION_INPUT_METADATA_READ[Blocked: metadata reads and message correlation]
    NOTIFICATION_NOTICE_METADATA[Blocked: attach notice metadata to submissions]
    NOTIFICATION_PRESENTATION[Blocked: compact frontend presentation]
    SESSION_INPUT_CONTRACT --> SESSION_INPUT_SUBMISSION
    THREAD_ARCHIVE_OWNERSHIP -. persistence expansion hold .-> SESSION_INPUT_SUBMISSION
    SESSION_INPUT_SUBMISSION --> SESSION_INPUT_METADATA_READ
    SESSION_INPUT_SUBMISSION --> NOTIFICATION_NOTICE_METADATA
    SESSION_INPUT_METADATA_READ --> NOTIFICATION_PRESENTATION
    NOTIFICATION_NOTICE_METADATA --> NOTIFICATION_PRESENTATION
```

Details: [Notification presentation and input metadata](notification_presentation.md).

### `SESSION_INPUT_CONTRACT` — review the input acceptance boundary

**Decision; may proceed during backfill.** Specify `{command_id, text, metadata}`, exact typed
attachments, service authentication/authorization, immutable retries and failure/receipt semantics
against the post-migration session identity. Resolve whether an existing submission row can be
extended. Review persistence-before-dispatch and retry recovery without implying offline execution
or silently moving runner admission. Output is a reviewed API/storage contract, not a new database.

### `SESSION_INPUT_SUBMISSION` — implement durable inputs and provenance

**Blocked on contract review and archive ownership.** Implement the chosen service-owned record
and API together. Enforce destination scope plus restricted notification-provenance permission;
server-stamp trusted origin and reject unauthorized/conflicting submissions. Translate only command
ID and text to the runner protocol. Test normal input, retries and ambiguous dispatch; do not add
an app-owned queue or expose metadata to runners/harnesses.

### `SESSION_INPUT_METADATA_READ` — authorized annotation reads

**Blocked on input submission.** Expose metadata by session/command identity and join existing
`origin_command_ids` in projections. Include pending/failed inputs, replay and retained historical
annotations without requiring a live notification inbox. Keep canonical runner Events unchanged.

### `NOTIFICATION_NOTICE_METADATA` — producer integration

**Blocked on input submission.** Attach notice identity/range metadata using existing delivery
command IDs. Preserve receipt reconciliation and explicit inbox acknowledgement. Verify the backend
path without the app; use automated integration coverage rather than requiring a provider outage.

### `NOTIFICATION_PRESENTATION` — compact notification rendering

**Blocked on producer and metadata read integration.** Compact authenticated notification-only
inputs, expand full text and render mixed human/notice messages normally with annotations. Missing
metadata falls back to text. Include visual coverage and one bounded real-notice check; no inbox
acknowledgement on render and no text-prefix provenance heuristic. Runners remain unaware.

### Subscription authorization before broader sources

```mermaid
flowchart LR
    SUBSCRIPTION_AUTHORIZATION_DESIGN[Decision: Action approval vs direct subscription policy]
    SUBSCRIPTION_AUTHORIZATION[Blocked: enforce reviewed creation and continuing source grants]
    SUBSCRIPTION_AUTHORIZATION_DESIGN --> SUBSCRIPTION_AUTHORIZATION
```

### `SUBSCRIPTION_AUTHORIZATION_DESIGN` — auto-allow and operator-approved subscriptions

**Decision.** Compare an Action-backed subscribe operation using existing auto-allow/operator
approval with authorization inside Notification Service; do not preselect another policy engine.
Review which callers may subscribe to which sources, targets, fields/filters, destinations and
lifetimes, and who can approve/delegate that access. Subscription creation approval is distinct
from continuing source access and from ownership of the destination inbox. Define renewal, scope
expansion, policy changes/revocation and what happens to already-retained entries.

Use Kubernetes as a concrete design case: namespace/resource/UID scope, object/status/event/log
content, name reuse and whether grants delegate the caller's existing read authority or explicitly
allow additional observation. A privileged watcher must not expose arbitrary cluster data merely
because the agent owns an inbox. Review argument examples that auto-allow narrow approved scopes,
require operator approval for additional scopes, and reject requests nobody can delegate. See the
[subscription authorization design](notifications.md#subscription-authorization-and-action-approval).
This is independent of selecting a messaging transport or fixing existing GitHub delivery gaps.

### `SUBSCRIPTION_AUTHORIZATION` — creation gate and continuing enforcement

**Blocked on the authorization decision.** If Actions is selected, implement its subscribe operation
and reviewed policy bindings; otherwise implement the chosen direct policy path. Keep Notification
Service the subscription/delivery authority in either case. Carry verified caller/decision scope
across the service boundary rather than substituting the executor's broad identity. Enforce the
same access contract on direct APIs, renewals and updates; no approval bypass by another endpoint.

Test auto-allow, pending approval, denial, restricted destinations, scope escalation and expiry/
revocation with controlled identities. No entry may be delivered beyond the reviewed source scope;
approval is not permission to wake a Sandbox or execute source content. Future Kubernetes sources
must depend on this contract/enforcement when promoted from the freezer. Ordinary authorized
subscription reads/cancellation and existing GitHub gap recovery need not wait for a broad redesign.

### GitHub notice reliability after missed updates

The operator reports that GitHub updates may sometimes be missed. This is a concrete reliability
concern, not proof that GitHub webhook delivery itself is at fault. Diagnose webhook receipt,
matching, inbox persistence and notice dispatch separately. Do not reopen waived broad provider
outage/refresh exercises; test the specific recovery contract with controlled missing webhooks.

```mermaid
flowchart LR
    GITHUB_NOTICE_RELIABILITY_DESIGN[Decision: eventual-state recovery vs agent fallback]
    GITHUB_NOTIFICATION_RECOVERY[Blocked: selected reconciliation or reminder mechanism]
    GITHUB_SHEPHERD_GUIDANCE[Candidate: honest monitoring and final-state verification guidance]
    GITHUB_NOTICE_RELIABILITY_DESIGN --> GITHUB_NOTIFICATION_RECOVERY
    GITHUB_NOTICE_RELIABILITY_DESIGN -. chosen guarantee wording .-> GITHUB_SHEPHERD_GUIDANCE
```

### `GITHUB_NOTICE_RELIABILITY_DESIGN` — delivery guarantee and fallback

**Decision.** Review the gap and choose the guarantee needed for PR shepherding: eventual awareness
of current head/check/review/merge state, or historical delivery of each event. Compare bounded
service-side reconciliation using existing durable shared GitHub refresh state with explicit agent
fallback checks, optionally scheduled reminders. Recommend the smallest reliable path with a stated
staleness bound/cost. A webhook subscription is not proof no changes occurred when it stays silent.
Snapshot polling cannot reconstruct all intermediate events, and a cron reminder alone is not
recovery if no active agent checks state. Detailed alternatives and questions are in the
[notification plan](notifications.md#missed-github-updates-and-shepherding-reliability).

### `GITHUB_NOTIFICATION_RECOVERY` — implement the reviewed recovery contract

**Blocked on the reliability decision.** If service reconciliation is selected, periodically compare
eligible shared subjects with authoritative GitHub state and durably emit deduplicated observations
for uncovered relevant changes. Reuse refresh leases, backoff and access checks; bound API load.
Distinguish observed state from a received webhook; do not fabricate delivery IDs or promise replay
of events the API cannot recover. If agent fallback is selected instead, provide its actual bounded
check/reminder mechanism and explicit limitations rather than just advising agents to remember.
Add `CRON_NOTIFICATIONS` as a prerequisite only if that reviewed implementation actually needs it;
a service refresh deadline need not introduce a general scheduler. Backend workers stay in-process.

Test a suppressed webhook, duplicate webhook/reconciliation races, changed head/check state and
restart/checkpoint recovery with a controlled GitHub peer. Observe one eventual update for the
promised scope, honest access/backoff state and no false claim of complete history. No live GitHub
outage or exhaustive historical event matrix is required.

### `GITHUB_SHEPHERD_GUIDANCE` — explain monitoring limits and completion checks

**Candidate for immediate baseline clarification; final wording follows the decision.** Treat
notifications as prompts to inspect authoritative current PR state, not evidence that the latest
head passed or that silence means no progress. Document the chosen fallback deadline/ownership and
how an agent notices unreliable monitoring. If reminders are chosen, state who runs them and that
notices do not start a stopped harness. Guidance accompanies the selected reliability behavior;
it must not advertise a polling/reminder guarantee before that mechanism exists.

## 3. Multiagent decisions before implementations

These are operator-reviewable decisions, not permission to implement every possibility. Drafts can
be developed together, but publish a coherent shared identity/authority vocabulary before downstream
APIs. Do not equate creating a resource, reading history, sending a message or receiving/acking it.

```mermaid
flowchart TD
    MULTIAGENT_MODEL[Decision: identities, relationships and native-child boundary]
    THREAD_READ_POLICY_DESIGN[Decision: history read grants]
    SANDBOX_COMPARTMENT_DESIGN[Decision: co-resident trust domains]
    SANDBOX_COMPARTMENT_BOUNDARY[Blocked: enforce selected trust boundary]
    THREAD_ARCHIVE_OWNERSHIP[Archive ownership cutover]
    THREAD_READ_POLICY[Blocked: scoped archive reads]
    AGENT_MESSAGING_DESIGN[Decision: send/receive RBAC and inbox vs direct delivery]
    AGENT_MESSAGE_INGRESS[Blocked: authorized send API and durable receipts]
    AGENT_MESSAGE_RECEPTION[Blocked: receiving, recovery and acknowledgement]
    AGENT_MESSAGING[Capstone: end-to-end agent messaging]
    THREAD_CREATE_POLICY[Decision: opening a session in an existing Sandbox]
    THREAD_CREATE_AUTHORIZATION[Blocked: implement session-create grants]
    AGENT_LAUNCH_POLICY_DESIGN[Decision: constrained Sandbox launch and delegation]
    AGENT_SANDBOX_LAUNCH[Blocked: enforce agent Sandbox-launch policy]
    MULTIAGENT_MODEL --> THREAD_READ_POLICY_DESIGN
    MULTIAGENT_MODEL --> SANDBOX_COMPARTMENT_DESIGN
    MULTIAGENT_MODEL --> AGENT_MESSAGING_DESIGN
    MULTIAGENT_MODEL --> THREAD_CREATE_POLICY
    MULTIAGENT_MODEL --> AGENT_LAUNCH_POLICY_DESIGN
    SANDBOX_COMPARTMENT_DESIGN --> SANDBOX_COMPARTMENT_BOUNDARY
    THREAD_READ_POLICY_DESIGN --> THREAD_READ_POLICY
    SANDBOX_COMPARTMENT_BOUNDARY --> THREAD_READ_POLICY
    THREAD_ARCHIVE_OWNERSHIP --> THREAD_READ_POLICY
    THREAD_ARCHIVE_OWNERSHIP -. persistence hold if new policy tables .-> SANDBOX_COMPARTMENT_BOUNDARY
    AGENT_MESSAGING_DESIGN --> AGENT_MESSAGE_INGRESS
    SESSION_INPUT_SUBMISSION[Service-owned input submission] -. if direct-input delivery selected .-> AGENT_MESSAGE_INGRESS
    SESSION_INPUT_METADATA_READ[Input provenance reads] -. if direct-input delivery selected .-> AGENT_MESSAGE_RECEPTION
    AGENT_MESSAGE_INGRESS --> AGENT_MESSAGE_RECEPTION
    AGENT_MESSAGE_RECEPTION --> AGENT_MESSAGING
    THREAD_CREATE_POLICY --> THREAD_CREATE_AUTHORIZATION
    THREAD_IDENTITY_NEW[Service-owned Session identity] --> THREAD_CREATE_AUTHORIZATION
    AGENT_LAUNCH_POLICY_DESIGN --> AGENT_SANDBOX_LAUNCH
    THREAD_ARCHIVE_OWNERSHIP -. hold on new service persistence .-> AGENT_SANDBOX_LAUNCH
```

### `MULTIAGENT_MODEL` — shared identity and authority vocabulary

**Decision; no runtime work implied.** Present concrete API examples for independent agents,
Sandboxes and Sessions, with creator, manager and parent/provenance represented separately. Ask
the operator to choose addressing/ownership and delegation semantics. No permission inheritance
from an organizational edge or preset. Review how native harness children could later be ingested:
linked execution in the same trust domain versus independently provisioned agents, addressability,
observability and which controls must remain unavailable. Native integration itself stays frozen;
this decision must allow explicit exclusion rather than require its implementation.

### `THREAD_READ_POLICY_DESIGN` — scoped history read policy

**Decision; draft in parallel with the shared model.** Review compartments versus exact-session
grants, who classifies/reclassifies histories and grants/revokes access, and caller replacement
semantics. Defaults expose no existing histories to workloads. Select raw read/list/follow scope;
read does not imply send/create, and no folded-read API is required for v1. Decide how revocation
applies to live feeds, discovery and linked evidence. Do not block this on a messaging transport.

### `SANDBOX_COMPARTMENT_DESIGN` — co-residency rule

**Decision.** Choose how a Sandbox's filesystem, credentials and shared ServiceAccount constrain
session compartments. Review whether incompatible sessions are prohibited from co-residing and
who may assign or change that scope. An archive ACL cannot isolate co-resident processes.

### `SANDBOX_COMPARTMENT_BOUNDARY` — enforce the selected boundary

**Blocked on the co-residency decision; new tables also wait for archive ownership.** Apply the
rule at Open, adoption and replacement; reject incompatible placement. Test shared filesystem/SA
cases and denied placements. Keep VM isolation a separate capability, not a fictional fix for
shared credentials inside one VM.

### `THREAD_READ_POLICY` — authorized retained-history access

**Blocked on archive ownership, reviewed read policy and compartment enforcement.** Enforce at
the owning backend across list, raw/native evidence, direct reads and feeds, including reconnect
and revocation. Keep app-only UI folds separate. Test allowed/denied histories, two principals,
deleted Sandboxes and revocation with deterministic service tests plus a bounded deployed auth check.

### `AGENT_MESSAGING_DESIGN` — send and receive contract

**Decision.** Merge the former overlapping `CROSS_THREAD_DELIVERY` design here. Present examples
of sender authentication, recipient discovery/opt-in, send grants, recipient read/ack grants and
administration. Compare Notification Service inbox delivery with direct session input and an
existing messaging channel; recommend the smallest fit. Define accepted, delivered, handled and
acknowledged separately; decide offline behavior, retention, batching, abuse limits and mailbox
ownership after Sandbox deletion. Reading a transcript does not authorize sending or acking.

Output includes the selected owner/API and explicit conditional prerequisites: a direct-input
implementation reuses `SESSION_INPUT_SUBMISSION` and provenance reads; a notification source reuses
inboxes without treating admission as acknowledgement. Neither branch is selected in this DAG.
Before dispatch, add the chosen branch's edges; do not require implementing both. New Sandbox
Service or app tables still wait for the migration hold. Pure Notification Service work need not
wait for unrelated archive schema once its contract is reviewed.

### `AGENT_MESSAGE_INGRESS` — authorized send and acceptance

**Blocked on messaging decision and its selected prerequisites.** Implement bounded payloads,
server-authenticated sender provenance, per-recipient send policy, idempotent message IDs and honest
acceptance receipts in the chosen authority. Test denied pairs, spoofing and retry/conflict behavior.

### `AGENT_MESSAGE_RECEPTION` — delivery, recovery and acknowledgement

**Blocked on ingress contract/implementation.** Implement selected recipient read/delivery/ack
operations, batching and recovery of unread work. Test revoked/deleted recipients, ordinary offline
catch-up and duplicate delivery without leaking payloads. Do not start/resume a harness implicitly.

### `AGENT_MESSAGING` — integrated messaging capstone

**Blocked on ingress and reception.** Demonstrate an authorized pair exchanging a message through
the selected API, with correct provenance and distinct receipt/ack states. Security-negative and
multi-replica retry cases belong in automated tests; no real provider outage requirement.

### `THREAD_CREATE_POLICY` — authorize session creation separately

**Decision.** Review caller scope to open in an existing Sandbox, accepted defaults, quotas,
creator visibility and revocation. Use the service-reserved Session identity, not a caller-invented
public UUID. Decide whether launch-and-open is a composition of separate grants, never an implicit
read/send/launch permission. This contract need not choose a durable offline command queue.

### `THREAD_CREATE_AUTHORIZATION` — implement session-create grants

**Blocked on create policy and new identity cutover.** Enforce scope/defaults and idempotent Open
lookup at the service boundary; test forbidden targets/overrides and a lost creation reply.

### `AGENT_LAUNCH_POLICY_DESIGN` — Sandbox launch and delegation policy

**Decision.** Review which callers can use which templates and resource budgets, mounts, images,
secrets, egress and Kubernetes/Action grants; presets are defaults, not authority. Define manager,
lifetime, parent termination, quota/fanout and revocation without automatic privilege inheritance.
Choose policy ownership and audit records before adding tables. State separately whether the
operation also opens a session; if so, depend on `THREAD_CREATE_AUTHORIZATION` for that composition.

### `AGENT_SANDBOX_LAUNCH` — constrained agent-requested launch

**Blocked on launch policy, idempotent create and the persistence hold.** Enforce the reviewed
effective spec and delegation server-side. Test allowed and forbidden launch parameters and
concurrent retries. Reuse Sandbox Service creation, not harness-native agent tools. Launch alone
does not grant history read, messaging, credentials or execution of another principal's Actions.

## 4. VM environment phases

The [KubeVirt plan](kubevirt_environments.md) contains completed prototype evidence and the detailed
provider design. Split implementation rather than making “VM support” one indivisible task. This is
an unranked candidate lane, not authorization for local Bazel in current containers. Co-design
runner dial-out with VM control networking before committing to guest inbound routing. Changing
connection direction need not move command durability or remove the runner journal.

```mermaid
flowchart LR
    RUNNER_TRANSPORT_DESIGN[Decision: service-dials-runner vs runner-dials-service]
    RUNNER_OUTBOUND_CHANNEL[Conditional: authenticated outbound runner channel]
    RUNNER_OUTBOUND_ROLLOUT[Conditional: migrate selected existing runners]
    VM_CONTROL_NETWORKING[Blocked: integrate selected VM control path]
    VM_IMAGE[Candidate: packaged guest and storage]
    VM_PROVIDER[Blocked: production provider and API]
    VM_EGRESS[Candidate: production admission and egress integration]
    VM_PROCESS_ISOLATION[Blocked: harness/process resource boundary]
    VM_LIFECYCLE[Blocked: integrated lifecycle]
    THREAD_ARCHIVE_OWNERSHIP[Archive ownership cutover] -. service-change scheduling hold .-> VM_PROVIDER
    RUNNER_TRANSPORT_DESIGN -. if outbound selected .-> RUNNER_OUTBOUND_CHANNEL
    THREAD_ARCHIVE_OWNERSHIP -. service-change scheduling hold .-> RUNNER_OUTBOUND_CHANNEL
    RUNNER_TRANSPORT_DESIGN --> VM_CONTROL_NETWORKING
    RUNNER_OUTBOUND_CHANNEL -. if outbound selected .-> VM_CONTROL_NETWORKING
    RUNNER_OUTBOUND_CHANNEL --> RUNNER_OUTBOUND_ROLLOUT
    VM_PROVIDER --> VM_CONTROL_NETWORKING
    VM_CONTROL_NETWORKING --> VM_LIFECYCLE
    VM_IMAGE --> VM_PROCESS_ISOLATION
    VM_PROVIDER --> VM_PROCESS_ISOLATION
    VM_IMAGE --> VM_LIFECYCLE
    VM_PROVIDER --> VM_LIFECYCLE
    VM_EGRESS --> VM_LIFECYCLE
    VM_PROCESS_ISOLATION --> VM_LIFECYCLE
    VM_LIFECYCLE --> SANDBOX_VM_ISOLATION[Capstone: selectable VM-backed Sandbox]
    SANDBOX_VM_ISOLATION --> LOCAL_BAZEL[Blocked: bounded local Bazel client in VM]
```

### `RUNNER_TRANSPORT_DESIGN` — runner dial-out and connection lifecycle

**Decision; design can proceed during backfill.** Compare today's service-initiated runner RPCs
with a runner-initiated long-lived channel to Sandbox Service, taking inspiration from Claude
RemoteIO's connection direction without adopting its wire protocol or lifecycle assumptions.
Present a recommended protocol and VM networking diagram for operator review. Define authenticated
environment/incarnation binding, connection ownership/fencing across replicas, heartbeat/liveness
states and timeouts, reconnect/replay cursors, command receipts and bounded backpressure. A lost
connection is not proof that the harness stopped or that a command failed.

Output must state whether v1 VMs use inbound or outbound control, which inbound ports/discovery
rules disappear, how existing container runners transition, and the selected implementation edges.
Keep runner journal/admission authority, offline queue policy and thin-runner redesign separate.
Detailed questions: [runner transport design](runner_discovery.md#outbound-control-channel-design).

### `RUNNER_OUTBOUND_CHANNEL` — implement the selected outbound transport

**Conditional on the transport decision; service changes wait for archive ownership.** Implement
runner/service connection handling, auth, replica routing/fencing, progress/heartbeat reporting and
cursor-based reconnect while retaining runner command/Event semantics. Test identity denial,
ordinary disconnect, stale connections, replay and flow control with controllable peers. Do not
require moving command admission centrally, native offline catch-up research or removing SQLite.

### `RUNNER_OUTBOUND_ROLLOUT` — migrate selected existing runners

**Conditional on outbound selection and channel implementation.** Migrate a bounded set using a
compatible guarded image transition, verify receipt/replay continuity and remove obsolete inbound
access for migrated environments. Define rollback and reject competing control paths; coexistence
across explicitly configured old/new environments is not silent per-request fallback. Fleet-wide
migration is not a prerequisite for first VM integration unless the reviewed design makes it one.

### `VM_CONTROL_NETWORKING` — integrate the reviewed connection direction

**Blocked on transport decision and VM provider; outbound implementation only if selected.** Wire
VM control reachability/authentication to the chosen path. An outbound channel may remove guest
control-port exposure and endpoint discovery; retain the independently needed outbound API/credential
proxy path. Image packaging and process-isolation work need not wait for this decision. Verify the
selected path on the actual VM network, not just a host-loopback transport test.

### `VM_IMAGE` — packaged guest and state storage

**Candidate.** Publish a digest-pinned guest with runner/harness versions, blank-disk setup and
retained state/workspace bounds. Check startup with both harnesses, without ad hoc downloads or
real credentials baked into the image. Reuse the proven prototype, not another platform evaluation.

### `VM_PROVIDER` — production provider API and lifecycle intent

**Blocked by scheduling hold on concurrent service surgery.** Integrate typed environment kinds,
templates/destinations, inventory, reconciliation, RBAC and UI. Container behavior remains intact.
Existing provider design can proceed during backfill; no uncoordinated service schema changes.

### `VM_EGRESS` — integrate production admission and proxy path

**Candidate.** Implement the selected launcher-injection/proxy route on the production stack.
Verify proxy-only credentials, routing, token replacement and denied cross-environment access;
check failure scope for the new admission configuration. Do not repeat the entire completed
prototype matrix or require simultaneous cluster-wide disasters.

### `VM_PROCESS_ISOLATION` — protect control from harness processes

**Blocked on image/provider.** Enforce aggregate memory/process/disk budgets and process-control
boundaries. Test representative tool/harness termination and bounded exhaustion to establish which
runner/control state survives and what needs durable recovery. This directly addresses agents
accidentally killing their own harness; guest or container packaging alone is not that guarantee.

### `VM_LIFECYCLE` — integrated lifecycle verification

**Blocked on provider, image, selected control networking, egress and isolation.** Exercise both harnesses through real service
routes with retained-state stop/start and a representative replacement; confirm identity, replay and
cleanup. Automated tests cover restart/concurrency branches. Additional live faults need a concrete
unresolved platform risk, not a Cartesian product of every component crash and lifecycle operation.

### `SANDBOX_VM_ISOLATION` — VM integration capstone

**Blocked on integrated lifecycle.** Publish the selectable VM environment and measured isolation
limits, with no implied existing-Sandbox conversion or live migration. Component evidence, not
absence of every imaginable failure, establishes the delivered contract.

### `LOCAL_BAZEL` — bounded local client in a VM

**Blocked on VM capstone.** Wire Bazelisk, storage and authenticated RBE/cache/BES; set CPU/memory/disk
budgets and cleanup. Run a representative build/test with the client inside the VM and actions
remote; check cancellation/cleanup while the harness stays responsive. Installed tools and working
hosted builds do not authorize local Bazel in agent containers. Hosted build acceptance is complete.

## 5. Independent UI and narrowly scoped service work

These candidates need no multiagent or VM decision. Any implementation that turns out to require
app/Sandbox Service database changes inherits the migration hold; non-mutating UI work does not.

### `THREAD_NOTIFICATION_INDICATOR` — pending notice status in the sidebar

**Candidate.** Expose authorized pending/next-eligible notice state and distinguish queued,
delivered and acknowledged states. Reconnect against backend state; any countdown is an estimate.
Independent of compact delivered-message rendering. Never acknowledge from viewing the sidebar.

### `THREAD_CACHE_WARMTH` — last-turn age with an honest heuristic

**Candidate.** Show authoritative last-turn age and optional provider-specific likely-cache-warmth,
with unknown state. It is not observed provider cache evidence. Accessible/reduced-motion behavior
and active/missing/completed-turn cases suffice; no new storage authority.

### `THREAD_BROWSE_PAGINATE` — bounded history browsing

**Candidate; data changes wait for migration.** Paginate/search the Thread listing with authorized
stable cursors, independent of deferred transcript full-text search. Verify ordering, navigation and
permissions rather than making the frontend load every Thread.

### `THREAD_SYNC_STOPPED_RECOVERY` — recover stopped UI synchronization

**Candidate; coordinate with archive read cutover.** Recover stopped feeds from retained cursors
without a manual refresh loop; show honest lag/failure and avoid duplicate rows. Follow the
[Thread sync plan](thread_sync/README.md), including bounded paging and error visibility. Changes to
archive ownership or app persistence wait for their migration nodes; client-only recovery can proceed.

### `CALLER_GRANT_VIEW` — unified view of existing grants

**Candidate.** Show effective grants for managed Sandboxes and unmanaged callers from their owning
APIs. Do not block showing current Action/egress grants on future managed Kubernetes grant kinds.
Clearly separate configured policy, effective scope and pending propagation; UI does not grant access.

## 6. Existing access and lifecycle follow-ups

These are bounded existing work, not dependencies on the broader multiagent model. Confirm current
source/deployment state with the relevant owner when dispatching; old acceptance notes are not live
observations. New database work inherits the migration hold.

```mermaid
flowchart LR
    PC_EGRESS_CREDENTIALS[Candidate: caller admission configuration] --> PC_EGRESS[Blocked: controlled egress cutover]
    CLAUDE_AI_SA[Decision: review caller authority] --> MANAGED_SA_RBAC[Blocked: account-owned Kubernetes grants]
    KUBERNETES_RBAC_POLICIES[Decision: reusable Kubernetes policy shape] --> MANAGED_SA_RBAC
    BOOTSTRAP_ATTEMPT_RECEIPT[Candidate: one durable bootstrap attempt] --> BOOTSTRAP_PROGRESS_CONTRACT[Blocked: asynchronous progress API]
    THREAD_ARCHIVE_OWNERSHIP[Archive ownership cutover] --> SANDBOX_LIFECYCLE_DURABILITY[Blocked: archive before managed storage deletion]
```

### `PC_EGRESS_CREDENTIALS` — label public-coder's Action Service caller

**Candidate; verify remaining configuration.** Admit the intended OpenClaw account to the dedicated
Action Service using its configured namespace and policy bindings. A label alone is not an execution
grant. Coordinate with the owner of the currently disabled/controlled workload before rollout.

### `PC_EGRESS` — public-coder-agent egress migration

**Blocked on caller admission and a controlled deployment.** Compare effective allowed/denied routes,
credential substitution and Action policy against the existing proxy, then do a reversible cutover.
Remove only unused OpenClaw-specific wiring; retain shared Iron/Haku consumers. Do not turn this
into an outage matrix. Source: [public-coder wiring](../../cluster/cdk8s/public_coder/proxy.py).

### `CLAUDE_AI_SA` — review the external caller's actual authority

**Decision.** Review the claude.ai account's Connection and arbitrary-shell Sandbox privileges,
Kubernetes scope and egress/Action grants. Record intended authority in generated configuration,
not ad hoc grants. Test an allowed and denied operation; do not add privileges as part of this review.

### `KUBERNETES_RBAC_POLICIES` — reusable policy shape

**Decision.** Compare named Role/ClusterRole bundles with Agentplane-owned rule sets. Review
namespace expansion, ownership, edit propagation and UI inspection. Existing static grant catalogs
are not runtime reusable policies; no general capability-profile framework is required.

### `MANAGED_SA_RBAC` — grants for accounts without a Sandbox

**Blocked on reviewed policy/ownership model.** Generalize account-keyed Kubernetes grants, including
owner/reconciliation/expiry when no Sandbox can own the binding. Do not fight GitOps over objects.
Existing grant views can ship first; add this grant kind when it exists. Keep ordinary authorization
and cleanup tests; no dependency on a new external-credential broker.

### `SANDBOX_RBAC` — bounded deployed grant checks

**Candidate; security-relevant remaining check.** Inspect the concrete managed-Sandbox grant path
and verify intended versus unrelated scope, including Role edits and credential-use boundaries,
without recording credentials. Use [agent RBAC](../../cluster/docs/agent_rbac.md) and existing tests;
only unresolved deployed wiring needs a live check, not a repeat of every already-covered operation.

### `NOTIFICATION_INGRESS_BOUNDARY` — bounded public-route security check

**Candidate; security-relevant deployment check, not a provider failure drill.** Existing tests
cover invalid signatures. Close the remaining route-wiring uncertainty with an unsigned webhook
request and a private-API request through the public hostname: both must be refused, without
creating subscriptions or inbox entries. Record the result once; no exhaustive provider matrix.

### `BINDING_SUBJECT_ARITY` — singular subject shape

**Candidate; schema changes wait for migration if they touch service/app persistence.** Align the
binding kinds on one explicit subject before adding multi-subject use. Preserve owner/replacement
and authorization semantics; this cleanup does not authorize broader grants.

### `BOOTSTRAP_ATTEMPT_RECEIPT` — one Sandbox bootstrap attempt

**Candidate.** Make repeated initialization return the retained attempt/result, including failed
or interrupted state, without rerunning a script. Test ordinary response loss/restart; an unknown
result is not automatic retry permission. A fresh initialization needs a distinct Sandbox.

### `BOOTSTRAP_PROGRESS_CONTRACT` — asynchronous start/status

**Blocked on durable attempt semantics.** Add authorized start/progress/result semantics without
holding an Open RPC through a long script. Keep successful bootstrap as the Open precondition
unless the operator reviews a change. Separate Sandbox initialization from per-session setup.

### `SANDBOX_LIFECYCLE_DURABILITY` — preserve archive before deleting storage

**Blocked on archive ownership.** Quiesce/fence and archive the final prefix before managed storage
removal. Explicitly handle an unreachable runner or incomplete state rather than claiming recovery.
Use existing same-storage suspension tests; a bounded deletion/archive check validates the new
boundary. No copied-volume portability or simultaneous multi-component crash requirement.

## Scope and retirement of stale gates

- Notifications keep workers in the HTTP service. Retention, worker extraction, idle-polling
  optimization and new-source wiring are frozen with triggers, not hidden release prerequisites.
- Existing GitHub error/backoff visibility, durable refresh reuse, hosted-build authentication and
  the Ducktape preset are accepted. No live provider-outage injection or repeat staging exercise is
  pending. Remaining broad provider-matrix exploration is frozen; ordinary auth/signature denial
  regression coverage belongs with the implementation, not an unbounded production checklist.
- Native subsessions and runner durability/thin-adapter redesign remain frozen. Transport direction
  has its own decision co-sequenced with VMs; neither that nor multiagent design unfreezes the broader
  runner-state redesign.
- Archive placement/store were removed as future tasks because the selected service-owned store and
  import/read code exist; this explicitly does **not** burn down backfill or writer/read cutover.
- `CROSS_THREAD_DELIVERY` is consolidated into `AGENT_MESSAGING_DESIGN`; `THREAD_OPEN_RELOAD_RECOVERY` is part
  of the identity cutover. Do not dispatch duplicate work under the old names.
- Existing security boundaries, data-preserving migration checks and representative deployment
  integration checks remain requirements. The freezer is not a waiver for a known data-loss or
  unauthorized-access bug; promote one when evidence makes it concrete.
