# Native subagent sessions: characterization gate

Before choosing a common session representation, characterize the pinned Claude Code and Codex
harnesses independently. A child must be created by the real harness, not synthesized by an
Agentplane adapter or inferred from parent prose. This is the evidence gate for
[`NATIVE_SUBAGENT_THREADS`](task_dag.md#native_subagent_threads--adopt-harness-native-subagents-as-threads),
not a change to its product priority or an implementation of session discovery.

The passing initial scenarios support the [harness-declared logical sessions proposal](native_session_discovery.md).
That plan sketches read-only discovery without treating the unmeasured matrix rows as implemented.

## Proposed ownership

The runner reports which native sessions exist, their observed lifecycle, and their parent/child
relationships. The Sandbox Service provides access to runner sessions; the integration app presents
them. A native child can share its parent's harness process and sandbox: recognizing it must not
launch another sandbox or turn the app into a backend session authority.

Discovery and control are separate capabilities. A visible child may have a transcript without
supporting independent input, interruption, or resume. A native agent handle is not necessarily an
independently addressable conversation. Keep that distinction until the matrix establishes it.

The runner is authoritative about its observations, not omniscient about native state. Losing its
connection does not prove that a child finished. Preserve historical sessions and distinguish an
observed terminal state from lost/unknown liveness. Recovery needs stable identity or an explicit
limit on reconciliation; replay must not create duplicate children.

## Test method and evidence

Use the existing [scripted harness suite](../harness_tests/README.md): real pinned binaries, loopback
model endpoints, synthetic tool calls, and native input/output traces. This removes model delegation
choice from the test. It also avoids live credentials and recorded production conversations.

For each case:

1. Assert that delegation is offered in the model-facing tool roster. Explicitly script the native
   delegation call and prove it caused a child model request. A parent saying it delegated is not proof.
2. Gate progress on requests/events, not sleeps. For concurrent children, route exchanges by native
   identity or distinct synthetic task markers; do not assume sibling request ordering. Bound every
   scenario and settle all exchanges so teardown catches leaked background work.
3. Assert the native relationship and lifecycle evidence, separately from the model API transcript.
   Model request IDs help the test drive the harness; they are not necessarily available to the runner.
4. Retain `stdin.jsonl`, `stdout.jsonl`, and `stderr.jsonl` through the existing `native_logs` fixture
   in Bazel undeclared outputs. Record the commit (which fixes the binary pins), launch/initialize
   options, test target, and CI invocation when reporting a finding. Sanitize any published excerpts.
5. Distinguish **tested**, **unmeasured**, and **unsupported with evidence**. A missing event in a
   bounded observation is not proof that the harness can never provide it through another interface.
   Once a limitation is established, assert that behavior rather than skipping the case.

The current pins in `MODULE.bazel` are Claude Code `2.1.252` and Codex `0.157.0`. The tests inherit
those pins; the older Claude observations in the protocol roster are not evidence for the new pin.
Codex's initial test explicitly exercises `features.multi_agent` and the `multi_agent_v1` namespace.
Its `multi_agent_v2` feature is a separate configuration to characterize, not an interchangeable alias.

## Matrix

**Added** means an executable assertion is in this change; use CI results for pass/fail status.
**Partial** identifies the exact remaining question. **Planned** means no new assertion yet.
The Claude defaults below follow the `2.1.252` CI trace: asynchronous launch and forwarded completed
child prose. They must not inherit expectations from the older `2.1.220` probe.

| ID  | Scenario and controlled stimulus                                        | Claude Code                                                                         | Codex app-server                                                                                              | Evidence needed before normalization                                                                        |
| --- | ----------------------------------------------------------------------- | ----------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| S1  | Spawn one background child with a unique task marker                    | Added: `Agent` call produces a child model request                                  | Added: namespaced `spawn_agent` produces a different model-request thread ID                                  | Creation evidence, native identity, parent linkage, and when each becomes available                         |
| S2  | Child runs a shell tool and returns a unique result                     | Added: child tool result round trip and forwarded tool frame's `parent_tool_use_id` | Partial: child tool result round trip; its model-request identity matches the spawn result                    | Which child tool inputs/results reach the runner, their attribution, and which require another subscription |
| S3  | Child completes; parent consumes result and continues                   | Added: async launch, parent turn end, child completion notification                 | Added: `wait_agent` result and native completed collaboration item identify the same child and its completion | Distinguish delegation-tool completion, child completion, and parent-turn completion                        |
| S4  | Observe child prose with forwarding defaults and explicit opt-in        | Partial: default forwards completed child prose with `parent_tool_use_id`           | Planned: compare parent stream with explicit child attachment                                                 | Full transcript vs summary; transport/subscription required; provenance of every message                    |
| S5  | Two children active together; finish in reverse spawn order             | Planned                                                                             | Planned                                                                                                       | Independent identities and terminal states; interleaved tool/text attribution; no imposed global ordering   |
| S6  | Child tool fails, then child handles it successfully                    | Planned                                                                             | Planned                                                                                                       | Tool failure must not be mistaken for session failure; preserve exit/error evidence                         |
| S7  | Child model request fails terminally; parent continues                  | Planned                                                                             | Planned                                                                                                       | Failure event/result and correlation; distinguish harness failure from a tool error                         |
| S8  | Interrupt child while its model exchange is held open                   | Planned: determine whether independent control exists                               | Planned: exercise native child control                                                                        | Accepted control vs observed interruption; sibling/parent isolation; too-late behavior                      |
| S9  | Parent completes, is interrupted, or exits while child is active        | Planned: foreground and background separately                                       | Planned                                                                                                       | Whether child stops, outlives parent turn, or disappears with process; no inferred completion               |
| S10 | Disconnect client while retaining the harness, then reconnect           | Planned: first establish supported transport                                        | Planned                                                                                                       | Enumeration vs events-only discovery; snapshot completeness; history replay and duplicate identity          |
| S11 | Restart harness and resume parent with completed and active children    | Planned                                                                             | Planned                                                                                                       | Persisted child identity/history, recoverable execution, and explicit unrecoverable/lost state              |
| S12 | Child delegates to a grandchild within configured depth limits          | Planned                                                                             | Planned                                                                                                       | Full ancestry vs root-only correlation; rejection at the limit without phantom sessions                     |
| S13 | Send child another input after it completes; attempt independent resume | Planned                                                                             | Planned                                                                                                       | Same session vs successor identity, supported addressing, and capability boundaries                         |
| S14 | Repeat core scenarios with alternate subagent configuration             | Planned: prose forwarding and background execution                                  | Planned: `multi_agent_v2`, then context-forking variants                                                      | Configuration-dependent behavior must not silently inherit the baseline contract                            |

### Claude communication surfaces

Do not treat every communication operation as another spawn, or a successful send receipt as proof
that the recipient consumed the message. Characterize these separately under the pinned tool roster:

- **`Agent` / `Task`:** creation and parent provenance. The model-facing `Agent` name and the native
  init roster's `Task` name differ in the current trace; aliases are not separate child sessions.
- **`SendMessage`, completed child (added):** address the returned agent ID; prove the follow-up
  reaches a child request containing its previous answer; correlate the send receipt and subsequent
  completion with the same child. Covered by
  `test_send_message_resumes_a_completed_child_and_task_output_reads_its_result`.
- **`SendMessage`, active child (planned):** gate the child's request, send another message, and
  determine when it is consumed and whether it interrupts work. Test child-to-parent and sibling
  delivery separately, including an unknown recipient. Do not infer delivery from a successful
  parent tool result.
- **`TaskOutput` (partial):** the communication test reads the completed child's follow-up result
  with `block=false`. Running-task reads and `block=true` need separate gates. The pinned tool
  describes itself as deprecated; test its behavior without making it the proposed discovery API.
- **`TaskStop` (planned):** stop a held-open child request; distinguish the tool receipt from an
  observed terminal notification and verify that parent and sibling work survive. Team shutdown
  messages, if advertised, are a separate cooperative protocol rather than equivalent cancellation.
- **`ListAgents` and configuration-specific team tools (planned):** first establish availability,
  scope, and feature gates. An entry in a tool roster does not prove that it enumerates all native
  children. Keep cross-session/remote messaging outside these same-harness loopback scenarios.

### Resume and child fate (planned)

Expand S10/S11 for both harnesses. The passing Claude `SendMessage` scenario reactivates a
completed child within the same live harness; it does not establish recovery after parent exit.
Distinguish client reattachment to a live owner, runner restart with retained journals, clean parent
harness exit followed by native resume, and parent crash followed by native resume. Record which
processes and native storage survive each case; these are not equivalent forms of resume.

For each applicable boundary, gate interruption with the child running (held at a model request or
tool), completed before its notification is consumed, completed after notification consumption,
failed, or cancelled. Include a pending follow-up message. Exercise conversational children and
non-conversation background tasks separately where supported; a task ID alone does not establish
a resumable conversation. Unsupported stimuli need evidence, not a fabricated terminal event.

Retain native traces from both process incarnations and answer:

- **Rediscovery:** does resume enumerate or redeclare children/tasks, with stable IDs and parent
  links? Is the inventory complete, historical, or only active? Can a previously known ID be queried?
- **Fate and timing:** is completion, failure, cancellation, continued execution, automatic restart,
  or unknown fate visible during handshake, after the first genuine input, through history, or only
  through an explicit query? Record each route separately. Parent model memory of a result is not
  independent runner-visible lifecycle evidence.
- **Delivery:** are terminal notifications replayed, omitted, or duplicated? Can the runner recover
  a result whose notification it missed? Does a queued message survive, disappear, or get delivered
  again, and what proves consumption rather than acceptance?
- **Execution:** does native resume restart child work, replace its ID, or replay a tool side effect?
  Use synthetic execution markers to distinguish retained history from fresh work. Do not send a
  follow-up merely to discover fate without recording that it can itself reactivate the child.

Use bounded phases: observe resume without input, then a genuine scripted parent input, then any
advertised status/history query. Negative observations apply only to that phase and route. Reuse
ordinary parent-resume fixtures, preserving native storage while starting a new harness process;
model-side gates establish the stimulus, but assertions about discoverability use native wire data.
Pin observed behavior per harness/configuration before advertising recovery capabilities.

### Transport-specific recovery investigation

Compare Claude `stream-json` with [`--sdk-url` RemoteIO](claude_remote_io.md), using the
same binary version and interruption points. The RemoteIO plan's static findings concern
`2.1.292`; they are not evidence of runner-pinned `2.1.252` behavior. Probe worker registration,
reinitialization, child/task inventory, transcript hydration, terminal-event replay, and whether
command delivery receipts expose anything about child execution. Keep server-supplied history
separate from state recovered by the harness itself. No transport cutover is implied.

Codex v1 and v2 require separate recovery probes. At tag `rust-v0.157.0`, upstream
[`multi_agent_resume.rs`](https://github.com/openai/codex/blob/rust-v0.157.0/codex-rs/core/tests/suite/multi_agent_resume.rs)
and its restore tests exercise v2 durable child identities and lazy loading after root restart.
This is source evidence for a promising path, not an app-server wire assertion or proof that the
v1 baseline automatically restores its children. Characterize unloaded identity, historical outcome,
and active execution separately; a loaded-thread list need not enumerate all known children.

The parameterized completed-child scenarios also probe a clean parent exit and fresh-process
resume. Both passed on commit `03596ef8` in
[CI](https://github.com/agentydragon/ducktape/commit/03596ef86d09913a11f521a69640e129cf60fea9/checks).
Parent model history retains the completed result, but querying the old child without reactivation
returns a missing-task error from Claude `TaskOutput` and `not_found` from Codex v1 `wait_agent`.
Codex also exposes `notFound` in the native collaboration item's `agentsStates`. Claude emits no
new `task_notification` during the tested resume/input/query sequence; the fixture's append-only
trace must be sliced at the process boundary to avoid counting first-process notifications as replay.
These observations cover neither crash recovery nor active children, v2, or RemoteIO.

### Initial executable coverage

The additions live in the existing tool-test targets, with their existing pinned-binary runfiles and
CI coverage:

- `//agentplane/harness_tests/claude:test_tools`:
  `test_subagent_tool_frames_are_correlated_with_the_parent_call` covers S1–S3 and the default half
  of S4. The child executes `Bash`; its forwarded tool frame points to the parent's `Agent` call.
  The async launch result, `task_started`, and `task_notification` must agree on child identity.
  This does not yet establish identity across restart or an independent child transcript API.
- `//agentplane/harness_tests/codex:test_tools`:
  `test_subagent_spawn_and_wait_report_the_child_identity` covers S1, the upstream part of S2, and
  S3. It handles parent/child model exchanges in either order and checks native collaboration items
  against the returned child ID. It does not yet assert child tool/text visibility on the parent
  connection, child attachment, or enumeration.

Single-agent tests keep their current configuration. Only the subagent Claude scenarios enable `Agent`, `SendMessage`, and `TaskOutput`;
only the new Codex scenario enables multi-agent tools. Neither changes production launch defaults.

CI should run the existing affected targets; no live-inference job or new secret is needed. CI runs these assertions against the pinned binaries. A first failure is diagnostic evidence to inspect,
not a reason to weaken an assertion into accepting either behavior. Fix the script if it did not
reach the intended stimulus; update a behavioral expectation only against the actual native trace.

## Gate for a shared session language

After the matrix establishes each harness's observable surface, record a behavior comparison with
links to test names and CI traces. Resolve these questions before changing runner/session protocols:

- What native key, scoped to which harness instance, identifies a child across live events and replay?
- Is the parent relationship native, derived from a delegation call, or unavailable?
- Can a reconnect enumerate live children, or is reconciliation limited to previously observed events?
- What is observable directly on the parent transport, through another subscription, or only in history?
- Which terminal states have explicit evidence, and when must liveness remain unknown?
- Which controls are independently supported, and which require the parent to act?

Then define only the common envelope the evidence supports: runner ownership, native identity and
provenance, parent linkage, observed lifecycle, attributed events, and capabilities. Preserve native
frames alongside it. Add deterministic adapter tests for normalization/replay once that adapter
exists; do not replace the real-binary tests with adapter mocks. Keep read-only presentation separate
from independently controlling children, and do not manufacture a complete transcript from a parent
summary.

## Codex multi-agent v2 discovery extension

`//agentplane/harness_tests/codex:test_v2_discovery` adds a separate configuration matrix
on the existing Codex **0.157.0** pin: `features.multi_agent=true` and
`features.multi_agent_v2=true`. The existing app-server driver already uses v2 JSON-RPC
methods; this extension specifically changes the **multi-agent feature/tool surface** from
`multi_agent_v1` to `collaboration`. It is not a production adapter or pin change.

| Case                           | Assertions / evidence                                                                                                             | Status                                          |
| ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| Root creation                  | `thread/start` mints ID; root has no parent; loaded enumeration includes it                                                       | Added, awaiting CI                              |
| Native child launch            | `collaboration.spawn_agent`, task name and `fork_turns=none`; `subAgentActivity.agentThreadId` agrees with child model-request ID | Added, awaiting CI                              |
| Live child snapshot            | `thread/read` identifies parent and shared session tree, active status; paginated loaded enumeration includes root and child      | Added, awaiting CI                              |
| Completed child, clean restart | Await native completed turn, restart server, resume root, enumerate and read historical child without resuming it                 | Added, awaiting CI                              |
| Completed child, crash         | Same read-only recovery after killing the server                                                                                  | Added, awaiting CI                              |
| Active child, crash            | Hold model request unanswered, kill server, observe request closure; recover identity/history without child reactivation          | Added, awaiting CI                              |
| Live client reconnect          | Retain server process, reconnect a separate client, compare enumeration and subscriptions                                         | Planned; stdio process restart is not this case |
| Alternate context/ancestry     | Context fork, concurrent children, grandchild, explicit child attachment and input                                                | Planned                                         |

The recovery probes query `thread/loaded/list`, `thread/list` with an explicit subagent
source filter, and `thread/read(includeTurns=true)`. They assert that reading the child does
not add it to loaded threads. No model-driven status query, child resume, or `followup_task`
is used; a bounded no-model-request observation follows the reads. Native request/response
traces and `recovery.json` retain exact fields for each case. Source inspection motivates
these expectations; CI must verify them before they become protocol findings.

A historical completed turn is distinct from a runtime `notLoaded` status. For an active
child killed with the process, retain and inspect the historical status rather than labeling
`notLoaded` as stopped/completed. The first probe asserts absence of the never-produced
child answer, not an invented terminal fate. Follow-up assertions should pin the actual
recovered status once the first wire capture is available.

The first CI capture (`6975829c`) confirms v2 emits `item/completed` with
`item.type=subAgentActivity`, `kind=started`, `agentThreadId`, and
`agentPath=/root/probe`; the enclosing `params.threadId` identifies the parent.
The v1 `senderThreadId` / `receiverThreadIds` shape does not apply to this item.
The capture also contains child `agentMessage` output under the child's own thread ID
and a parent-stream `subAgentActivity(kind=completed)`. Live read assertions reached
shared session-tree identity and completed child history, but the incorrect v1-shaped
assertion stopped the first run before recovery. Recovery expectations remain unverified.
