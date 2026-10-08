# Native subagent sessions: characterization gate

Before choosing a common session representation, characterize the pinned Claude Code and Codex
harnesses independently. A child must be created by the real harness, not synthesized by an
Agentplane adapter or inferred from parent prose. This is the evidence gate for
[`NATIVE_SUBAGENT_THREADS`](task_dag.md#native_subagent_threads--adopt-harness-native-subagents-as-threads),
not a change to its product priority or an implementation of session discovery.

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

**Added** means an executable assertion is in this change, not that it has passed CI.
**Partial** identifies the exact remaining question. **Planned** means no new assertion yet.
No row below claims a measured result before execution.

| ID  | Scenario and controlled stimulus                                        | Claude Code                                                                         | Codex app-server                                                                                              | Evidence needed before normalization                                                                        |
| --- | ----------------------------------------------------------------------- | ----------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| S1  | Spawn one background child with a unique task marker                    | Added: `Agent` call produces a child model request                                  | Added: namespaced `spawn_agent` produces a different model-request thread ID                                  | Creation evidence, native identity, parent linkage, and when each becomes available                         |
| S2  | Child runs a shell tool and returns a unique result                     | Added: child tool result round trip and forwarded tool frame's `parent_tool_use_id` | Partial: child tool result round trip; its model-request identity matches the spawn result                    | Which child tool inputs/results reach the runner, their attribution, and which require another subscription |
| S3  | Child completes; parent consumes result and continues                   | Added: async launch, parent turn end, child completion notification                 | Added: `wait_agent` result and native completed collaboration item identify the same child and its completion | Distinguish delegation-tool completion, child completion, and parent-turn completion                        |
| S4  | Observe child prose with forwarding defaults and explicit opt-in        | Partial: default excludes child prose from standalone assistant text frames         | Planned: compare parent stream with explicit child attachment                                                 | Full transcript vs summary; transport/subscription required; provenance of every message                    |
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

Single-agent tests keep their current configuration. Only the new Claude scenario enables `Agent`;
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
