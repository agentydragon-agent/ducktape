# Claude Code and Codex protocol adapters

Status: **native evidence inventory plus post-capture adapter target**. The first experiment code
drives Claude and Codex directly with explicit provider-specific JSON scenario tests. Adapter
behavior is extracted only after those captures show the real intersection. This document
distinguishes provider capability from the current Ducktape runner's implementation choices.
License-aware references are in
[Implementation reuse and prior art](implementation_reuse.md).

## Adapter and version policy

V0 does not require a declarative compatibility-profile subsystem. Each provider mode is a Python
adapter with unit tests, offline fixture replay, and a small set of real-harness captures. The code
must fail clearly on malformed required responses and preserve unknown native frames, but it should
not reject an otherwise working harness merely because its version string is new or unavailable.

Use recent resolved Claude Code and Codex versions available in the test environment. Record the
self-reported version, package/image digest, launch arguments, capabilities, model route, and native
state paths when they are known. A capture proves behavior for the recorded binary and
configuration; it is evidence, not a formal product matrix or a reason to overengineer version
selection.

Ducktape's existing evidence spans several Claude versions and currently packages Codex `0.144.1`.
Those facts are useful provenance, not required target pins for the new tree. Version changes should
prompt capture/test review when practical. Correctness gates are protocol behavior and test
evidence, not equality among package metadata, self-report, and a predeclared profile.

The implementation begins in a new top-level, non-Haku tree. Existing `haku/runner`,
`haku/cli_protocol`, and `haku/console` code and fixtures are behavior evidence only; the new adapters
must not import them or make Haku storage/session assumptions part of the control-plane contract.

### Model endpoint and subscription authentication boundary

**Repository evidence.** Haku Console already runs both adapters through the cluster's existing
subscription gateway:

- Claude Code speaks Anthropic Messages to LiteLLM, which forwards the native Messages surface to
  CLIProxyAPI's Claude subscription session.
- Codex app-server speaks OpenAI Responses to LiteLLM, which forwards the native Responses surface
  to CLIProxyAPI's Codex/ChatGPT subscription session.

The deployed route is configured in
[`cluster/k8s/haku/console/config.yaml`](../../../cluster/k8s/haku/console/config.yaml) and asserted by
[`cluster/k8s/litellm/app/test_litellm_config.py`](../../../cluster/k8s/litellm/app/test_litellm_config.py).
CLIProxyAPI owns login, OAuth files, and refresh. In the proven Haku Console profile, the bridge sees
only a configured endpoint and an inert placeholder; the Console egress fence substitutes the real
scoped LiteLLM virtual key. Consumer OAuth handling is therefore not part of either provider adapter
or the common control-plane protocol.

## Claude Code adapter

### Launch and transport

**Repository evidence.** Ducktape currently launches Claude Code with stream JSON in both directions. The orchestration-relevant argv in `haku/runner/claude/options.py` includes:

```text
claude
  --output-format stream-json
  --verbose
  --include-partial-messages
  --input-format stream-json
```

Other launch configuration is intentionally outside this orchestration document. Protocol probes
also pass `--print`; the capture harness should record the actual argv and test both relevant modes
instead of turning the difference into a formal compatibility profile.

The local wire is newline-delimited JSON over child stdin/stdout. Conversation frames and control frames share that ordered stream.

The Claude Agent SDK is not a separate provider runtime: the pinned Python SDK launches the Claude
Code binary as a subprocess with stream-JSON input and output. It is useful prior art for framing,
message routing, and compatibility tests. The bridge nevertheless owns the CLI wire directly so
native records, initialization, admission evidence, interruption, and reconnect behavior are not
hidden behind an SDK abstraction. See Ducktape's
[CLI protocol ownership decision](../../../haku/plans/cli_protocol_ownership.md) and
[pinned SDK/CLI wire analysis](../../../haku/runner/docs/mid_turn_input.md#claude-code-stream-json-protocol).

### Initialization

The adapter sends a correlated control request:

```json
{
  "type": "control_request",
  "request_id": "req_...",
  "request": { "subtype": "initialize" }
}
```

Control responses correlate through `response.request_id`. The current runner writes initialize
first but does not await its response before entering the command loop; it relies on stdin ordering.
The new bridge should capture the response and expose initialization as an explicit runtime state.
It may still pipeline later writes only if adapter tests and recorded harness behavior prove that
safe.

### Prompt submission

A normal prompt is a conversation frame, not a control request:

```json
{
  "type": "user",
  "message": { "role": "user", "content": "..." },
  "parent_tool_use_id": null,
  "uuid": "client-generated-uuid"
}
```

The UUID is important provider evidence. Claude's command-lifecycle frames can report admission,
start, completion, and queued-command cancellation against that identity. The bridge reports
`native_admitted` only after the configured evidence threshold, not merely after writing bytes to
stdin.

### Streaming output

Observed native classes include:

- `assistant` messages with text, thinking, and tool-use blocks;
- `user` messages carrying tool results;
- terminal `result` records;
- partial `stream_event` records, including text and tool-input JSON deltas;
- `system`, command-lifecycle, rate-limit, and compaction records;
- correlated control responses.

Completed assistant/tool blocks are authoritative snapshots. Partial deltas exist for live display
and exact provenance; the adapter's projector deduplicates completed copies rather than emitting
duplicate messages or operations.

Ducktape includes a scrubbed real Claude capture with `Write`, `Read`, successful `Bash`, and failed
`Bash` behavior at `haku/runner/claude/testdata/diverse_session.jsonl`. This is valuable projection
evidence, not a recovery test.

### Tool mapping

Claude tools arrive uniformly as `tool_use` blocks with `id`, `name`, and `input`. Results arrive as `tool_result` blocks, with additional structured output in native result fields.

Initial mappings:

- `Bash` -> common `shell`;
- `Read` -> `file.read`;
- `Write`/`Edit` -> a deliberately broad `file.change` projection when useful;
- `Glob` / `Grep` -> file `search` when their exact semantics are known;
- any other named structured call -> common `tool`.

The projection need not reproduce Claude's patch/application semantics. Exact tool names, inputs,
results, ids, and unknown fields remain in the cited native frames.

### Interrupt

Claude exposes a correlated `interrupt` control request. The response can acknowledge the request,
but a clean product outcome additionally requires native command/turn/result evidence. The adapter
records:

1. interrupt requested centrally;
2. request written and correlated;
3. control response received;
4. affected prompt/turn terminal evidence;
5. any remaining queued prompt lifecycle.

Connection loss or process kill is not rendered as a successful interrupt.

### Mid-turn steering

**Repository measurement.** Sending another user frame during an active tool-using turn has been
observed at a later tool boundary. Continuous prose generation may have no such boundary, so input
can remain waiting until the turn completes. The wire frame itself does not declare whether the
sender intended “steer this run” or “submit the next prompt,” and it is not the same contract as an
RPC targeted at an explicit turn id.

Do not freeze this observation into a neutral `boundary_queued_input` contract yet. The raw matrix
must determine whether Claude exposes one native queue or several, how ordinary active-run prompts
differ from intended steering if at all, which lifecycle records indicate queued/admitted/delivered,
and whether pending frames can be cancelled. Only then can the later adapter label the behavior
without inventing certainty.

The experiment suite must test at least:

- delivery during a long tool call;
- delivery between two tool calls;
- delivery during continuous prose;
- delivery racing terminal result;
- interruption while a steering input is queued;
- normal user-frame submission while active, separately from steering intent;
- multiple queued inputs and their delivery order; and
- whether any queued command can be dequeued before admission or delivery, including the exact
  evidence for supported, too-late, and unsupported outcomes.

### Native resumption

Claude emits a native session identity and supports session-resume functionality, but the current
runner's `resume_from` argument is only a cursor for replaying runner journal frames to the central
Console. It does **not** restart the Claude process with provider-native session resumption.

The new adapter must discover and persist the native state locations needed by the tested Claude
version. The provider session id remains in the native stream and may be indexed from there.
Resumption claims are split:

- **completed-turn memory**: after process/Pod death, resume and answer from prior model
  context without relying on workspace files;
- **workspace survival**: PVC files survive independently of provider context state;
- **in-flight recovery**: determine how a partially executed turn appears after resume and whether
  side effects might repeat;
- **queued input recovery**: determine whether unadmitted/admitted mid-turn input survives process
  death.

Only the first two are plausible default guarantees. The latter two remain explicit experiments.

## Codex app-server adapter

### Launch and transport

**Repository evidence.** Ducktape launches:

```text
codex app-server --listen stdio://
```

The local wire is JSON-RPC-shaped newline-delimited JSON over stdio. The parser accepts optional `jsonrpc` fields and is fail-soft around unknown envelopes.

A committed real-binary test starts the app-server against a local fake OpenAI-compatible HTTP
endpoint and proves the app-server transport without paid inference. It does not prove model-context
semantics. A future cross-provider harness-in-the-loop fake-LLM test is tracked in the experiment
plan.

### Initialization

Codex requires an explicit stateful handshake on each app-server connection:

1. request `initialize` with client metadata and supported capabilities;
2. await the response;
3. send `initialized` notification;
4. start or resume a thread;
5. subscribe to and process server requests/notifications.

Requests before initialization are rejected. The bridge records returned server metadata and
negotiated capabilities as native/debug evidence for the tested adapter run.

### Durable versus ephemeral threads

The current Ducktape runner sends `thread/start` with `ephemeral: true`. That is appropriate for a
runner whose own journal is the continuity boundary, but it cannot support app-server cold resume:
ephemeral threads are in-memory and have no stored path.

This design uses durable Codex threads for resumable sandboxes:

```json
{
  "method": "thread/start",
  "id": 10,
  "params": {
    "cwd": "/workspace/project",
    "ephemeral": false
  }
}
```

It persists `CODEX_HOME` on the PVC, records `result.thread.id`, and resumes after process or Pod
replacement with:

```json
{
  "method": "thread/resume",
  "id": 11,
  "params": { "threadId": "thr_..." }
}
```

The control plane independently fences runtimes and waits for the prior workload to terminate before resuming a durable thread for writing. Whether Codex also enforces a single writer is treated as an experiment result, not relied on as the fence. Read APIs can inspect history without loading it.

In v0 the product Thread maps one-to-one to this durable Codex thread across Runtime generations.
The Pod, bridge, and Sandbox placement may change; the product and native Codex thread identities do
not change merely because compute was replaced. A future shared app-server may host several Agents,
but each Agent still maps to a distinct product Thread and distinct Codex thread.

### Prompt and turn flow

A new turn uses a request such as:

```json
{
  "method": "turn/start",
  "id": "bridge-42",
  "params": {
    "threadId": "thr_...",
    "clientUserMessageId": "input_...",
    "input": [{ "type": "text", "text": "Run the tests" }]
  }
}
```

The response supplies an initial turn object. `turn/started` is execution admission. Item
notifications stream work, and `turn/completed` supplies terminal status. The adapter uses both the
JSON-RPC request id and native thread/turn/item ids.

Only one ordinary turn is expected to execute per thread at a time. The initial matrix must still
send another ordinary `turn/start` while one is active and record whether app-server rejects it,
queues it, accepts it for later, or behaves differently. Do not assume in advance that the central
service must own that queue merely because the current Ducktape runner does.

### Streaming output

Initial item types relevant to the product include:

- `userMessage`;
- `agentMessage` plus `item/agentMessage/delta`;
- `reasoning` plus summary/content deltas;
- `plan` and plan updates;
- `commandExecution` plus output deltas;
- `fileChange` plus patch updates;
- structured tool-call items;
- web search, image, input request, collaboration, compaction, and provider-specific items.

`item/started` opens a UI item. `item/completed` is authoritative for that item's final state and
result. `turn/completed` is terminal for the turn but is not a substitute for consuming the full
item stream.

Ducktape currently has synthetic projection coverage for messages, reasoning, commands, and
terminal turns, but no committed real-provider Codex Thread capture equivalent to Claude's
fixture. Creating one is a priority experiment artifact.

### Tool mapping

- `commandExecution` -> common `shell`, preserving stable common fields such as command, cwd,
  status, output, exit code, and duration when they are exposed unambiguously;
- provider-only fields such as `commandActions`, execution source, and item ids may be copied into
  `provider_debug` for display/diagnosis, but common control logic must not depend on them;
- `fileChange` -> deliberately broad `file.change` path/action summaries when useful; exact patch
  and application semantics remain in native frames;
- any other named structured call -> common `tool`;
- unknown item types -> common `generic` only when useful, while the complete native frame remains
  independently stored.

Codex app-server can issue JSON-RPC requests to the client as well as notifications. The adapter
must either handle each request type enabled by its initialization or return an explicit unsupported
response; treating stdout as notifications only would deadlock an active turn. A general
interactive-request protocol is deferred beyond v0.

### Interrupt

Codex exposes an explicit `turn/interrupt` request targeted at `threadId` and `turnId`. The product
records request acknowledgement separately from the eventual `turn/completed` interrupted/failed
status. A process kill remains a different failure.

### Mid-turn steering

Codex exposes `turn/steer` for the active thread/turn and can associate a client user-message id.
Unlike Claude boundary-queued input, it targets an explicit native turn. The adapter reports steering
accepted only after the JSON-RPC response; the resulting user item and continued turn stream are
then normal timeline evidence.

The current Ducktape runner does not call `turn/steer`; it queues every additional prompt for a later
`turn/start`. That is repository behavior, not yet the control-plane decision. The raw tests keep
these actions explicit and separate:

- call native `turn/steer` against an active turn;
- call native `turn/start` again while a turn is active;
- attempt any documented or discovered native cancellation/dequeue path;
- stop sending a not-yet-written request in the test driver as a distinct local control; and
- call native `turn/interrupt`.

The result determines whether the eventual future-turn queue belongs in the orchestrator,
bridge/runner, or app-server and whether any dequeue operation can honestly cross that boundary.

The experiment suite covers steering during command execution, reasoning/message streaming, and a
race with turn completion. It separately captures standard submission while active, app-server
queue behavior if any, dequeue timing, multiple-input ordering, and queued-input fate across
interrupt and app-server death.

### Native resumption

Codex has the clearest provider-native cold-resume contract of the two adapters: durable rollout
state plus `thread/resume`. The product still must prove, for each recorded/tested binary and
persistent layout:

- completed-turn memory after app-server kill;
- cold resume after Pod replacement;
- single-writer release after abrupt death;
- active-turn history after app-server or Pod kill;
- whether resume exposes an interrupted marker, partial items, or an uncertain active state;
- continuity after Sandbox suspend/resume;
- no accidental use of `ephemeral: true` when a run claims durable resume.

## Optional direct-LLM adapter

A later `harness-bridge --mode direct` can run an agent loop against a model API while emitting the same common protocol. It does not pretend to be Claude Code or Codex and has no provider-native harness session to resume.

The adapter would own:

- model request/stream assembly and stable request ids;
- assistant and reasoning delta reconstruction;
- structured operation-call assembly and result submission;
- bounded operation output, spill references, and truncation markers;
- model-facing history, context limits, and compaction;
- retries, cancellation, partial-response recovery, and terminal classification.

Its native records are the exact model API requests/responses plus loop-state transitions. Its session continuity comes from the durable model-facing history stored by the control plane, not from a CLI session id.

This mode is intentionally after the two native vertical slices. It exists to support API-only agents or providers without a suitable harness, not to make Claude/Codex inherit a home-grown loop and lose their native behavior.

## Side-by-side semantics

| Capability                | Claude Code stream/control                           | Codex app-server                                                 | Common product behavior                     |
| ------------------------- | ---------------------------------------------------- | ---------------------------------------------------------------- | ------------------------------------------- |
| Connection handshake      | initialize control request/response                  | `initialize` then `initialized`                                  | runtime initialized                         |
| New turn input            | user stream frame with UUID                          | `turn/start` with client message id                              | future common submit shape follows captures |
| Mid-turn input            | queued user frame observed at a boundary             | targeted `turn/steer`                                            | steering with provider-specific timing      |
| Normal input while active | native queue/lifecycle behavior to capture           | active-run `turn/start` behavior to capture                      | queue owner remains an experiment result    |
| Dequeue pending input     | lifecycle cancellation if exposed; otherwise unknown | native cancellation if any; otherwise not-yet-written local stop | final common behavior follows captures      |
| Interrupt                 | interrupt control request                            | `turn/interrupt`                                                 | request plus observed terminal outcome      |
| Assistant stream          | partial events plus completed blocks                 | item deltas plus completed item                                  | message/reasoning items                     |
| Shell                     | `Bash` tool use/result                               | `commandExecution`                                               | `shell` operation                           |
| File edits                | `Write` / `Edit` tool use/result                     | `fileChange`                                                     | file operation                              |
| Structured tool call      | named tool use/result                                | structured tool-call item                                        | `tool`                                      |
| Harness Thread id         | Claude session id                                    | Codex thread id                                                  | opaque harness-issued `harness_thread_id`   |
| Cold resume               | CLI-native resume; exact behavior to prove           | durable `thread/resume`                                          | new runtime with continuity evidence        |
| Current runner gap        | no native process restart/resume                     | starts ephemeral thread; no steer                                | new design must change both                 |

V0 runs one product Thread and one active harness Thread per bridge process. The controller may
create the product Thread before any harness starts. On `start_thread`, the adapter lets Claude or
Codex mint its native resumable identity and emits it through the common facade as an opaque
`harness_thread_id`. On `resume_thread`, the controller returns that same opaque id without knowing
whether it is a Claude session id or Codex thread id.

Codex app-server can host multiple independent native threads, but multiplexing them would couple
failure, resource, and fencing domains. If a future deployment accepts that coupling, each Agent
still has a distinct product Thread and harness Thread even when several share one Sandbox or
process. Claude's selected print-mode process is not assumed to offer the same multiplexing
contract. Any relaxation requires measured lifecycle and isolation semantics.

## Post-capture adapter contract target

The following is a design target, not an API that the initial capture suite must implement. The
first tests use provider-specific JSON and native ids directly so they can test-drive unknown
protocol behavior without hiding it behind the abstraction under investigation. Revise this facade
after the harness-by-scenario matrix answers queue ownership and delivery/admission questions.

The bridge calls a provider-neutral asynchronous facade:

```text
start_thread(config, persistent_paths) -> thread_activation(harness_thread_id)
resume_thread(harness_thread_id, config, persistent_paths) -> thread_activation(harness_thread_id)
submit(input_id, content) -> accepted_by_adapter
steer(input_id, turn_id, content) -> accepted_by_adapter | unsupported | too_late
cancel_input(input_id) -> dequeued | already_delivered | unsupported | unknown
interrupt(turn_id) -> request_accepted | unsupported | too_late
events() -> async stream<adapter_emission>
shutdown(deadline) -> exit_observation
```

`turn_id` is the common id previously emitted by that adapter, never a native Claude/Codex id.
Likewise, the adapter mints common item/operation ids when native concepts become observable and
keeps any provider-specific mapping private. Claude can make native resume a launch-time choice;
Codex initializes app-server first and then starts or resumes a thread. Those differences remain
inside the adapter implementation.

`adapter_emission` is a tagged union with two externally persisted forms:

- `native.frame`: the exact bridge-to-harness or harness-to-bridge JSON frame, direction, sequence,
  and timing;
- `common.event`: a provider-neutral Thread/Turn/Input/message/reasoning/operation/lifecycle event
  with source native sequence or wire-record references.

The adapter emits native frames even when they have no common projection. Common projections may
be lossy, especially for file edits, but they always link back to the exact native evidence. The
bridge durably appends emissions in order before forwarding them to the controller.

### Adapter-owned state

Native request ids, Claude command UUID lifecycle state, Codex thread/turn/item ids, outstanding
JSON-RPC correlations, and common-to-native turn/item mappings are adapter implementation state, not
controller API fields. The adapter also tracks whether each input is only queued locally, written to
the native wire, acknowledged/admitted by the harness, or observably delivered at a provider
boundary.

State transitions needed after bridge/process restart are appended to the existing bridge log and
may be compacted into an adapter checkpoint on the PVC. The controller stores the opaque
`harness_thread_id`, common ids, input states, and emitted evidence; it never steers or interrupts by
native id. If an adapter cannot reconstruct a safe mapping after recovery, it emits an explicit
unsupported or uncertain observation rather than asking the controller to understand the native
protocol.

`steer` is intended to target an active common turn, and dequeue must remain distinct from turn
interruption. The exact meaning of `submit` while active, which component owns pending prompts, and
whether `cancel_input` can cross into a native queue are intentionally unresolved. The provider
matrix answers those questions before the facade becomes normative.

The bridge does not synthesize provider admission, delivery, or terminal state when the adapter
lacks evidence.

## Regression gates

An adapter/image combination is eligible for automatic recovery only when all required scenarios
pass for a recorded harness run:

- baseline native-wire fixture;
- idle process restart and native resume;
- completed-turn memory after cold resume;
- interrupt lifecycle;
- provider-specific steering semantics;
- Pod replacement with PVC continuity;
- central disconnect/replay without duplicate exact records;
- raw shell, file, and structured-tool protocol coverage;
- active-turn loss classified honestly.

A binary upgrade should rerun the focused capture suite before promotion. Golden fixtures first
catch framing/parser changes; later projector tests can consume the accepted fixtures. Live probes
catch behavior not guaranteed by schemas. An unknown version string alone is not a failure when the
protocol behavior and tests pass.
