# Claude Code and Codex protocol adapters

Status: **evidence-backed adapter design**. Exact behavior is version-pinned and must be revalidated by
the [experiment suite](experiments.md). This document distinguishes provider capability from the
current Ducktape runner's implementation choices.

## Compatibility policy

The initial Ducktape image pins Claude Code `2.1.198` and Codex `0.144.1`. Each supported adapter declares a compatibility profile containing:

- harness binary and package version;
- launch arguments and relevant environment switches;
- protocol/schema version or capability response;
- provider/model configuration family;
- bridge adapter version;
- persistent native-state layout;
- experiment-suite result and artifact digest.

An unknown harness version may run in an explicit experimental mode, but it does not inherit the
resume, interrupt, steering, or projection guarantees of a passing profile.

Operational native records are retained for routine projection. A restricted, short-retention raw
evidence tier can preserve exact bytes for reprojection and protocol diagnosis.

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

Other launch configuration is intentionally outside this orchestration document. Protocol probes also pass `--print`; this argv discrepancy must be resolved or deliberately included in the compatibility profile before probe results are treated as production evidence.

The local wire is newline-delimited JSON over child stdin/stdout. Conversation frames and control frames share that ordered stream.

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
The new bridge should capture the response and expose initialization as an explicit attempt state.
It may still pipeline later writes only if the pinned compatibility test proves that safe.

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
and exact provenance; the projector deduplicates completed copies rather than emitting duplicate
messages or operations.

Ducktape includes a scrubbed real Claude capture with `Write`, `Read`, successful `Bash`, and failed
`Bash` behavior at `haku/runner/claude/testdata/diverse_session.jsonl`. This is valuable projection
evidence, not a recovery test.

### Tool mapping

Claude tools arrive uniformly as `tool_use` blocks with `id`, `name`, and `input`. Results arrive as `tool_result` blocks, with additional structured output in native result fields.

Initial mappings:

- `Bash` -> common `shell`;
- `Read` -> `file.read`;
- `Write` -> `file.write`;
- `Edit` or patch tool -> `file.patch`;
- `Glob` / `Grep` -> file `search` when their exact semantics are known;
- any other named structured call -> common `tool`, retaining the original name and blocks.

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

**Repository measurement.** Sending another user frame during an active tool-using turn is admitted
and observed at a later tool boundary. Continuous prose generation may have no such boundary, so
input can remain waiting until the turn completes. This is not the same contract as an RPC targeted
at an explicit turn id.

The adapter therefore represents Claude steering as `boundary_queued_input` with its UUID and
command lifecycle, not as immediate mutation of the currently sampled model response. The UI can
say “queued for the next Claude boundary” and later “admitted” when evidence arrives.

The experiment suite must test at least:

- delivery during a long tool call;
- delivery between two tool calls;
- delivery during continuous prose;
- delivery racing terminal result;
- interruption while a steering input is queued.

### Native resumption

Claude emits a native session identity and supports session-resume functionality, but the current
runner's `resume_from` argument is only a cursor for replaying runner journal frames to the central
Console. It does **not** restart the Claude process with provider-native session resumption.

The new adapter must store the provider session id and deliberately select the native state
locations needed by the pinned Claude version. Resumption claims are split:

- **completed-turn memory**: after process/Pod death, resume and answer from prior conversational
  context without relying on workspace files;
- **workspace survival**: PVC files survive independently of conversation state;
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

A committed real-binary test starts the pinned app-server against a local fake OpenAI-compatible HTTP endpoint and proves the app-server transport without paid inference. It does not prove conversation semantics.

### Initialization

Codex requires an explicit stateful handshake on each app-server connection:

1. request `initialize` with client metadata and supported capabilities;
2. await the response;
3. send `initialized` notification;
4. start or resume a thread;
5. subscribe to and process server requests/notifications.

Requests before initialization are rejected. The bridge records the returned server metadata and
negotiated capabilities in the attempt compatibility profile.

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

The control plane independently fences attempts and waits for the prior workload to terminate before resuming a durable thread for writing. Whether Codex also enforces a single writer is treated as an experiment result, not relied on as the fence. Read APIs can inspect history without loading it.

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

Only one ordinary turn runs per thread. Additional normal inputs can be centrally queued as future
turns; they must not be presented as mid-turn steering.

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
terminal turns, but no committed real-provider Codex conversation capture equivalent to Claude's
fixture. Creating one is a priority experiment artifact.

### Tool mapping

- `commandExecution` -> common `shell`, preserving command, cwd, status, output, exit code, duration, source, and native `commandActions`.
- `fileChange` -> `file.patch`, preserving per-path kind and diff.
- any other named structured call -> common `tool`, preserving arguments, result/error, and native context as extensions.
- unknown item types -> common `generic` plus full operational native payload.

Codex app-server can issue JSON-RPC requests to the client as well as notifications. An initial compatibility profile must either support each enabled request type or reject that profile during initialization; treating stdout as notifications only would deadlock an active turn. A general interactive-request protocol is deferred beyond v0.

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
`turn/start`. The new adapter must keep these operations distinct:

- **steer active turn** -> `turn/steer`;
- **queue future turn** -> central durable queue, later `turn/start`;
- **interrupt** -> `turn/interrupt`.

The experiment suite covers steering during command execution, reasoning/message streaming, and a
race with turn completion.

### Native resumption

Codex has the clearest provider-native cold-resume contract of the two adapters: durable rollout
state plus `thread/resume`. The product still must prove, for the exact binary and persistent layout:

- completed-turn memory after app-server kill;
- cold resume after Pod replacement;
- single-writer release after abrupt death;
- active-turn history after app-server or Pod kill;
- whether resume exposes an interrupted marker, partial items, or an uncertain active state;
- continuity after Sandbox suspend/resume;
- no accidental use of `ephemeral: true` in a resumable compatibility profile.

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

| Capability           | Claude Code stream/control                 | Codex app-server                      | Common product behavior                |
| -------------------- | ------------------------------------------ | ------------------------------------- | -------------------------------------- |
| Connection handshake | initialize control request/response        | `initialize` then `initialized`       | attempt initialized                    |
| New turn input       | user stream frame with UUID                | `turn/start` with client/native ids   | accepted, dispatched, admitted         |
| Mid-turn input       | queued user frame observed at a boundary   | targeted `turn/steer`                 | steering with provider-specific timing |
| Future input         | provider queue/lifecycle behavior          | central queue then later `turn/start` | queued future turn                     |
| Interrupt            | interrupt control request                  | `turn/interrupt`                      | request plus observed terminal outcome |
| Assistant stream     | partial events plus completed blocks       | item deltas plus completed item       | message/reasoning items                |
| Shell                | `Bash` tool use/result                     | `commandExecution`                    | `shell` operation                      |
| File edits           | `Write` / `Edit` tool use/result           | `fileChange`                          | file operation                         |
| Structured tool call | named tool use/result                      | structured tool-call item             | `tool`                                 |
| Session identity     | Claude session id                          | Codex thread id                       | provider-native session reference      |
| Cold resume          | CLI-native resume; exact behavior to prove | durable `thread/resume`               | new attempt with continuity evidence   |
| Current runner gap   | no native process restart/resume           | starts ephemeral thread; no steer     | new design must change both            |

## Adapter contract to the bridge

Each provider adapter implements these phases:

```text
prepare_launch(start | resume, native_session_id, config, persistent_paths) -> launch_plan
launch(launch_plan) -> child
initialize(child) -> native_capabilities
activate_session(start | resume, native_session_id) -> native_session
submit(input_id, content) -> admission_observation
steer(input_id, native_turn_id, content) -> admission_observation
interrupt(native_turn_id) -> request_observation
read_native_record() -> exact record
classify_terminal(record) -> optional terminal observation
shutdown(deadline) -> exit observation
```

Claude can make native resume a launch-time choice; Codex initializes app-server first and then starts or resumes a thread. The split above supports both. Methods can return provider-specific extensions. The bridge does not synthesize a provider admission or terminal state when the adapter lacks evidence.

## Compatibility gates

A provider image is eligible for automatic recovery only when all required scenarios for its
profile pass:

- baseline turn and projection fixture;
- idle process restart and native resume;
- completed-turn memory after cold resume;
- interrupt lifecycle;
- provider-specific steering semantics;
- Pod replacement with PVC continuity;
- central disconnect/replay without duplicate common events;
- shell, file, and structured-tool normalization;
- active-turn loss classified honestly.

A binary upgrade invalidates the gate until the suite is rerun. Golden fixtures catch parser and
projection changes; live probes catch behavior not guaranteed by schemas.
