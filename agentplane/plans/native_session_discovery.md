# Harness-declared logical sessions

Status: **proposed**, grounded in the passing characterization tests from
[PR #9435](https://github.com/agentydragon/ducktape/pull/9435). This is a possible next implementation
of `NATIVE_SUBAGENT_THREADS`, not a shipped runner contract or a priority change. The
[characterization matrix](native_subagent_sessions.md) remains the evidence inventory.

## Direction

Let a harness create native children. Its runner adapter interprets the native protocol evidence
and declares those children as logical sessions. The runner durably owns their identities,
relationships, observations, and availability; the Sandbox Service exposes them, and the app
presents them as related Threads.

This does not require adding an Agentplane-specific declaration API to Claude Code or Codex. Their
existing messages are the declaration inputs. The adapter is responsible for translating those
messages into a small shared vocabulary without manufacturing capabilities the harness lacks.

A child declaration must not spawn another harness process, run setup, allocate a sandbox, or
copy the parent's command queue. Several logical sessions can share one harness process and its
native state. Recognition is initially read-only; independently controlling a child is a later,
evidence-gated capability.

## What the tests establish

For Claude Code `2.1.252`:

- `system/task_started` supplies `task_id`, originating `tool_use_id`, task type, and background
  status. The parent `Agent` tool result exposes the same identity as `agentId`.
- Forwarded child tools and completed prose carry `parent_tool_use_id`. Their `session_id` can
  still be the parent's, so that field alone is not a child identity.
- `system/task_notification` identifies the child and its completion outcome.
- `SendMessage` to a completed child resumes that same agent ID. The child's next model request
  retains its earlier answer; a later completion notification names the same child. `TaskOutput`
  can retrieve its later result. A send receipt is not evidence that the child has finished.

For Codex app-server `0.157.0`, with `multi_agent_v1` enabled:

- Native `collabAgentToolCall` items expose `senderThreadId` and, on successful spawn completion,
  `receiverThreadIds`. The spawn result's child ID agrees with the separate child model request.
- A completed wait item exposes the same child identity and its completion through `agentsStates`.
- Spawn-tool completion and child-work completion are different observations.

The runner can obtain these identities from native traffic. The model endpoints used by the tests
are a test oracle, not a proposed discovery dependency. The tests do not yet prove full Codex child
transcript delivery, complete native enumeration, nesting, or identity continuity after native
restart. The tested Codex v1 surface must not stand in for its v2 configuration.

## Vocabulary and ownership

Use **logical session** for a native conversational participant that can accumulate history and
potentially do more work later. Keep these concepts separate:

- **Execution owner:** the durable runner resource that launches and supervises the harness and
  retains its native state. Today this is coupled to a root session; with harness-minted root IDs it
  must be reservable before that root is declared. It is not the semantic parent of every descendant.
- **Logical session:** a root conversation or a discovered native child. It owns attributed
  conversation history, not necessarily a process, workspace, or independently usable control API.
- **Parent relationship:** the native delegation ancestry, supported by evidence. Preserve the
  spawning call as provenance; a later message from a sibling does not reparent the recipient.
- **Activity:** one observed period of work within a session. Finishing it does not delete or
  permanently close the session. Use native turn IDs where available; otherwise retain the native
  activity evidence without claiming an exact model-turn boundary.
- **Native background task:** a harness-specific category, not automatically a logical session.
  A shell job, file transfer, or remote task must not become a conversation merely because it emits
  a `task_started`-shaped event. V1 recognizes only evidenced agent/conversation types.
- **Thread:** the app's conversation view and operator annotations. It is not the session registry
  or another execution authority. Follow the existing [layering contract](../docs/thread_layering.md).

The runner's inventory means **all sessions it has durably learned about**, not necessarily all
children hidden inside the harness. Report the distinction. Current native enumeration coverage
is insufficient to advertise an exhaustive live-native snapshot.

## Identity and declaration

Use the same declaration model for roots and children. Today root runner IDs are client-selected;
the proposed harness-minted-root flow below separates requesting creation from observing a native
conversation. Persist an opaque Agentplane logical ID and its native binding before publication.
Use the canonical logical identity direction in the layering plan; do not require existing root
storage paths to be rekeyed here.

A session descriptor should carry:

- Logical session ID, execution-owner ID, and parent ID when established.
- Origin kind: explicitly opened root or harness-discovered child.
- Native harness kind and qualified native handle, including its identity scope.
- Discovery evidence and the spawning call's native identity when available.
- Observed activity/availability, transcript coverage, and supported access modes.
- Optional display metadata supplied by the harness, treated as untrusted content.

Native handle lookup needs a persisted namespace, not a bare `task_id` or `threadId`. Qualify it by
execution owner, harness kind, native handle kind, and native identity scope. Initially, a native
scope cannot be assumed to survive a new harness incarnation. Runner replay on retained storage
reuses its saved mapping; matching a newly launched harness to old children requires positive
continuity evidence. Neither PID reuse nor equal descriptions proves continuity.

Within that scope, repeated discovery upserts the same child. Alternative references such as
Claude's `task_id`, `agentId`, and delegation `tool_use_id` become evidence-backed aliases, not new
sessions. A continuation call can add an alias without changing ancestry. Conflicting mappings
must retain the native evidence and surface a reconciliation problem, not silently merge children.

Declare only when there is native evidence of an actual child identity. A tool-call start with no
returned child ID is a pending delegation in the parent's history, not yet a child session. An
error before creation must not leave a phantom child. If an ID is first observed at completion,
allow late discovery without inventing a previously observed running interval.

## The single-agent case: harness-minted root IDs

A single-agent run is the smallest declaration case: one execution owner, one root declaration,
no parent relationship. The harness is authoritative about the native conversation's identity and
existence; the caller requests creation rather than declaring that a conversation already exists.

Keep three identifiers distinct:

- **Creation request ID:** caller-chosen correlation/idempotency key. Retrying it retrieves the same
  creation attempt; it is not a native or logical session ID.
- **Native session ID:** minted by the harness and learned from native protocol evidence.
- **Agentplane session reference:** a stable public logical identity bound to the qualified native
  ID. Prefer an opaque runner-assigned ID so native scope/format changes do not rekey public history.
  Making the native ID itself public is a possible alternative, but it still needs harness/owner
  scope; a bare native ID is not a globally unique Agentplane reference.

The proposed flow is:

1. The client requests a new root with a spec and creation request ID, optionally including the
   first input with its own command ID. It does not need to supply a future session ID.
2. The runner durably reserves the execution owner, native state location, and creation intent.
   It may reserve the eventual logical ID and journal here, but reports **pending creation**, not
   an observed native session. Setup and launch failures belong to this attempt.
3. The adapter starts the harness and requests a new native conversation. Native evidence supplies
   its ID; the runner commits the binding and a root `SessionDeclared` observation with no parent.
4. The client receives the declared session reference and can list, attach, and use the proven root
   controls. Identity binding must not change the journal's origin or discard pre-declaration evidence.
5. Later turns and explicit native resume reuse that binding when continuity is established.
   Creating another native conversation is another declaration, not a relabeling of this session.

The two harnesses have different declaration timing:

- **Codex:** the existing adapter already obtains a harness-minted `thread.id` from `thread/start`.
  That reply can declare the root before the first `turn/start`. Today it is stored underneath a
  separately client-chosen runner session ID; the new creation flow removes that client-ID prerequisite.
- **Claude:** the existing runner currently generates a UUID and passes `--session-id` on fresh
  launch; the adapter's `handshake()` returns that preselected ID after `initialize`, not an ID minted
  by the handshake response. To exercise harness-minted identity, omit the fresh-launch override
  and bind the ID from an observed native
  session-bearing frame. Do not assume `initialize` announces it: the exact earliest reliable
  declaration boundary needs a pinned test, including the no-input case.

If the ID is not revealed until input starts, the API must not deadlock by requiring an attached
session before accepting the first input. Persist that input in the creation attempt's existing
journal, dispatch it using that command ID when the native transport is ready, then bind the resulting
session declaration without resubmitting the input.
The pending creation reference can serve launch progress and declaration evidence until attachment
is possible. A UI may show a pending conversation, but it must not report a native session as already
created. Do not insert a synthetic user prompt merely to force the harness to allocate an ID.

Creation idempotency is not native exactly-once execution. If the runner crashes after requesting a
native conversation but before durably recording its ID, a retry of the same creation request must
not blindly start another one. Recover through positively identified native state/protocol evidence
where supported; otherwise report an ambiguous creation outcome. A JSON-RPC request ID or a saved
creation intent alone does not prove the native operation is safe to repeat. Test that crash window
before promising automatic recovery. Changed specs under the same creation key are rejected.

This proposes separating **create**, **observe/attach**, and **explicit resume** in the runner/service
contract rather than overloading `Open(unknown_id, spec)` with a guessed future ID. Use the existing
command/journal machinery for the attempt and first input, not another execution queue. Retain the
existing root mappings and history; implementation should make an atomic contract cutover rather
than add a tolerant second interpretation of `Open`. The first child-discovery slice may keep today's
root creation path, but that is an explicit scope boundary, not the final identity model.

Root and child discovery then converge: both commit the same descriptor and declaration observation;
only their cause, parent linkage, and capabilities differ. A child declaration has native delegation
provenance rather than a client creation request, and does not allocate a new execution owner.

### End-to-end: provision a sandbox and start its first session

One common client flow can work for either harness. The operation names below are illustrative,
not claims about the current API. The caller can be a UI backend, CLI, or another agent.

1. **Client → Sandbox Service: `CreateSandbox`.** Supply a creation request ID, sandbox template,
   and authorized workload configuration. The service authorizes and provisions the sandbox, then
   returns a stable sandbox reference and a provisioning operation to follow. Allocated is not yet
   ready: wait for the runner to become reachable and required sandbox initialization to succeed.
2. **Client → Sandbox Service: `StartSession`.** Supply that sandbox reference, a session-creation
   request ID, the harness/model/workspace/instructions spec, and optionally the initial input with
   its own command ID. The service authorizes access, resolves the runner, and forwards the request;
   it does not operate the harness itself.
3. **Runner: durable acceptance.** Reserve the execution owner, native state directory, logical
   session reference `S`, and journal the creation intent and any initial input before dispatch.
   Return `S` in a starting/pending state and expose startup progress. Retrying the creation request
   finds this attempt, not another launch. `S` is usable to track the attempt before it proves that
   a native conversation exists.
4. **Adapter ↔ harness: native creation.** Codex runs `initialize`, then `thread/start`, binds the
   returned `thread.id`, and submits the saved input through `turn/start`. Claude can initialize in
   stream-json mode, submit the saved input, and bind the ID from a session-bearing native frame.
   Alternatively its adapter can preselect the ID through `--session-id` and wait for native
   confirmation. These choices do not change the caller's flow or justify resending the input.
5. **Runner → Sandbox Service → client: declaration and events.** Commit the qualified native-ID
   binding and declare root `S` with no parent and the creation request as provenance. The client
   continues using the same `S` for follow/attach and proven root commands; it need not address a
   Codex thread ID or Claude conversation ID. Startup acceptance, native existence, input
   confirmation, and work completion remain distinct facts.
6. **If the harness delegates later:** native evidence declares child `S2`, with parent `S` and the
   same execution owner. The child enters the same inventory with its proven coverage/capabilities;
   Agentplane does not provision another sandbox or launch another process to recognize it.

Creation failure remains inspectable through the pending attempt. The ambiguous native-creation
crash window described above still applies; request deduplication does not make native creation or
first-input delivery exactly once. No app database record is required for runner-side declaration.

## Proposed observation flow

Names here are illustrative; implement them in the existing runner Event language, not a parallel
command/event API:

1. **Session declared:** upsert the descriptor from native creation or later discovery evidence.
2. **Activity observed:** report running, idle with a last-work outcome, or unknown. Carry the
   native turn/activity key when available and preserve the exact evidence for the inference.
3. **Session capabilities observed:** update transcript coverage and any proven access modes.
4. **Session availability changed:** record native loss, confirmed disposal, or verified recovery
   separately from a completed activity. Historical identity and history remain retained.

For Claude, a plausible sequence is:

```yaml
- observation: session_declared
  session_id: child-session
  execution_owner_id: root-session
  parent_session_id: root-session
  native_handle:
    kind: claude_agent
    id: native-agent-id
    scope: native-incarnation-scope
  provenance:
    spawning_tool_use_id: native-spawn-call
- observation: activity_observed
  session_id: child-session
  state: idle
  last_work_outcome: completed
- observation: activity_observed
  session_id: child-session
  state: running
  evidence_kind: native_continuation_activity
```

These are semantic examples, not claims that each transition has a dedicated native frame. In
particular, successful `SendMessage` alone cannot justify running or message-consumed state. The
adapter must use the relevant native activity/content evidence. Keep unknown state when that
boundary is not observable.

Route native frames before applying conversation logic. Otherwise a child's forwarded assistant
frame can mutate the parent's item state, active turn, or command receipts. Parent history keeps
the delegation tool and its result; child history gets child-attributed content. Do not replace
child history with the parent's summary or render a forwarded child answer as parent-authored prose.

Claude routing initially joins `parent_tool_use_id` to the discovered child mapping. Codex uses
native thread identities where those are actually supplied on the client-visible stream. A frame
may provide both parent-tool and child-state observations; derive both with separate attribution.
Unresolved frames remain raw evidence until attribution is known. Never guess the root as the
recipient of otherwise ambiguous child traffic. Bound any in-memory correlation buffer and retain
an explicit unresolved state when it cannot be resolved.

## Runner protocol and storage seams

Today [`runner/protocol.proto`](../runner/protocol.proto), [`Session`](../runner/session.py), and
[`SessionRecord`](../runner/store.py) couple a session to a launch spec, native persistence, process,
and active turn. `ListSessions` lists those stored sessions; `Open` with a spec may launch/resume.
The first implementation must separate the logical-session descriptor from execution ownership.

Proposed public behavior:

- Extend `ListSessions` to include discovered children and their execution owner, ancestry, origin,
  availability, and coverage. A stopped owner does not erase its historical children.
- Extend `Attached` with the same descriptor. Retain `Open` without a spec as observation-only;
  attaching a discovered child never starts its owner. Initial child attachments are read-only.
  An idle child can still receive future activity on that attachment; do not end its stream merely
  because its most recent task completed. Describe owner-process health separately from child activity.
- Reject launch/setup/spec mutations on discovered children. A child must not acquire a fake copy
  of the parent's `SessionSpec`: its actual prompt/model/settings may differ or be unknown.
- Reject unsupported child commands before admission. Do not route a child command to the parent's
  stdin just because they share a process. Existing root command idempotency remains unchanged.
- Include replayable discovery in the owner's Events. A client first obtains the retained inventory,
  then follows the owners from the returned cursors to cover declarations racing the snapshot.
  Define and test that list/follow handoff, including inventory reconciliation for execution owners
  created after the snapshot; do not rely on the app noticing an incidental tool card.

Prefer retaining one logical Event stream per child so the current one-Session/one-Thread view model
remains meaningful. This needs an explicit evidence and storage design before protocol rollout:

- Preserve a raw native frame once at its execution owner. Child-derived Events must cite the
  owner's qualified `EventOrigin`; today's `Event.source_sequences` only addresses the emitting
  source and cannot express this cross-session reference. Extend the evidence language atomically
  and update readers/importers rather than treating the parent's sequence as a child-local sequence.
- Each session retains its own replay cursor; cursors from parent and child are not comparable.
  Sibling arrival order at the runner is not a universal native causal order.
- Persist the identity mapping and relevant event routing before publication. Crashes between
  declaration, child creation, and content append must replay to one child and one derived fact.
  Today journals are per-session SQLite databases: an in-memory dispatch into two journals is not
  an atomic commit. Choose a shared transactional boundary or a replayable, idempotent projection
  from the owner's durable evidence before implementing fan-out. Do not add a second command queue.
- If using replayable projection, record a durable applied prefix and deduplicate each derived
  observation by its source evidence and target. Keep already-published origins stable on replay;
  reinterpreting history after an adapter upgrade needs an explicit policy, not silent regeneration.
- Archive enough referenced owner evidence with child history that Raw remains resolvable after
  sandbox deletion. The Sandbox Service remains a live access service, not a new archive authority.

These are required design gates, not a claim that the existing journal already supplies multi-session
transactions. The read-only first slice should settle them without refactoring command scheduling
or adding independently executable child sessions at the same time.

## Discovery, capability, and recovery boundaries

Treat coverage as at least identity-only, lifecycle/result-only, or partial attributed transcript.
Only advertise a complete transcript when the harness boundary actually supports that claim. Codex
starts with its proven collaboration evidence; separately subscribing to a native child, if required,
is still an open test. A runner must not synthesize missing child text from a parent wait result.

Describe native message/control routes separately from exposed runner commands. Claude's proven
parent-tool `SendMessage` route does not establish a direct driver-input API for children. Likewise,
`TaskOutput` retrieving a result does not prove general history enumeration. A capability becoming
visible does not bypass the Sandbox Service's existing authorization or grant child callers another
ServiceAccount's authority. Shared-process children are not isolation boundaries.

On owner transport/process loss, mark previously active children unknown/lost as observations of
availability; preserve their last known outcomes. Do not convert loss into successful completion or
claim remote/native execution stopped unless the harness proves it. On runner restart, reload the
retained inventory without launching anything; on explicit native resume, reconcile only what the
native protocol can establish. Absence from a partial snapshot is not proof of deletion.

The [resume/fate characterization](native_subagent_sessions.md#resume-and-child-fate-planned)
must distinguish live reattachment, runner replay, clean native resume, and crash recovery. For each
child, retain the last observed work outcome separately from current availability and the evidence
that supports reconciliation. Report whether fate can be recovered automatically, only after input,
or via an explicit query; a remembered parent summary is not a new child lifecycle observation.
Deduplicate replayed terminal notifications without hiding a genuinely new work episode. A missing
notification, an empty partial inventory, or a not-found response does not establish successful
completion or cancellation. Preserve unknown fate when the native protocol cannot resolve it.

Do not automatically rerun unresolved work or use a child-message operation as a status probe:
reactivation may execute work again. Characterize native resume's own automatic restart behavior
and side-effect replay before offering it as recovery. Read-only acceptance must cover retained
outcomes with unknown current availability; stronger fate reconciliation remains test-gated.

Independent child input, interruption, native resume, nested ancestry, enumeration, and new identity
scope reconciliation remain gated by the matrix. Do not enable parent-injected tool calls as a hidden
implementation of a supposedly independent child command.

## Implementation slices and acceptance

1. **Evidence extraction and routing.** Pin root ID allocation/declaration timing for both harnesses,
   including Claude without `--session-id` and without initial input. Extend native wire types only
   for fields consumed; add
   adapter tests for declaration, aliases, attribution, and completion using the characterized native
   events. Retain unknown frames. Verify child events cannot settle parent commands or turns.
2. **Durable declaration and read-only child sessions.** Decide whether harness-minted root creation
   ships in this slice or follows the existing-root discovery path. If included, test creation retries,
   delayed declaration/first-input delivery, and crashes before/after the native ID binding. Resolve
   qualified evidence references and the cross-journal
   commit/replay design. Persist descriptors and attributed child streams; implement read-only
   list/attach. Crash-test every declaration/fan-out publication boundary and duplicate replay.
3. **Service and presentation.** Expose inventory/history through the existing Sandbox Service API.
   The app discovers children from runner evidence and presents linked Threads with coverage and
   availability indicators. No app database write is a prerequisite for declaring a native child.
4. **Broader recovery and control.** Add only the capabilities demonstrated by further tests:
   alternate subscriptions, native enumeration, independent controls, restart identity, nesting,
   and Codex v2. These are not prerequisites for honest read-only discovery.

Acceptance for the read-only slice must run both pinned harnesses through the runner with the
integration app unavailable. Prove that an ordinary parent action creates a discoverable child,
IDs and aliases agree, attributed content does not contaminate the parent, and child completion
does not destroy its identity. Claude's completed-child follow-up must reuse the child session.
Also cover late discovery, duplicate events, unknown native kinds, missing correlation, concurrent
siblings, attachment during discovery, owner loss, runner restart with retained storage, and explicit
rejection of child launch/control. Assert the honest lower coverage for Codex until additional native
transcript delivery is demonstrated. UI acceptance then proves presentation, not backend authority.
