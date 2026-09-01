# Common harness protocol and timeline vocabulary

Status: **initial v0 design**. Claude Code and Codex are the two required reference adapters. The
common model describes their useful intersection without discarding provider-native records.

This is the central product protocol used by the server, bridge, database, and UI. It is not a
replacement for native provider protocols. Its relationship to A2A 1.0 is described in
[A2A fit and protocol layering](a2a.md).

## Design rules

1. **Two native adapters from the start.** A concept is common only when it has a defensible Claude
   and Codex mapping, or when it is explicitly a control-plane concept such as Sandbox lifecycle.
2. **Wire evidence precedes projection.** The bridge sequences and durably records native units
   before the server creates common events.
3. **Common does not mean lossy.** Every projected event cites native evidence when native evidence
   exists. Unknown provider records remain queryable.
4. **Inputs are independently admitted.** A turn has one initiating input and may have additional
   steering inputs; those inputs do not collapse into one boolean state.
5. **Transport replay is not semantic replay.** Duplicate bridge delivery is deduplicated. Accepted
   user input is not automatically resent to a provider after an uncertain crash.
6. **Lifecycle and activity are separate axes.** Sandbox existence, Runtime and process state, and turn
   activity are not one overloaded status field.
7. **PostgreSQL is authoritative.** A globally ordered thread timeline is assigned when Postgres
   accepts records/events; runtime-local native sequences alone do not order replacement runtimes.
8. **Origin is explicit.** Human prompts, Agent messages, automations, subscriptions, and external
   events all enter through the same durable input path with a provenance envelope. A provider-facing
   user role does not imply that a human typed the content.

## Identities and ordering

The initial stable identifiers are:

- `thread_id`: durable ordered interaction identity for one speaking Agent/harness;
- `sandbox_id`: durable environment record;
- `runtime_id`: one bridge/Pod incarnation;
- `runtime_generation`: monotonically increasing Sandbox-scoped ordinal and fencing epoch for the
  n-th authorized Runtime;
- `native_process_generation`: child-process generation within one runtime;
- `native_session_id`: provider conversation identity;
- `input_id`: one accepted user input, whether initiating or steering;
- `turn_id`: one common provider execution bracket;
- `native_turn_id`: provider turn identity when one exists;
- `item_id`: one common message, reasoning item, or operation;
- `operation_id`: stable lifecycle identity for one operation;
- `thread_seq`: Postgres-assigned durable order for common events and anchored wire records.

`Runtime` names the concrete Pod/bridge incarnation; `runtime_generation` says which ordinal
incarnation is authorized. `Session` is reserved for the provider-native resumable identity. Agent
identity, Sandbox identity, and any future authorization principal are distinct.

The native sequence key is:

```text
(runtime_id, native_process_generation, native_seq)
```

It is dense only within one child process generation. `thread_seq` supplies the total durable order
across control-plane events, process restarts, replacement runtimes, and native records. When events
are received concurrently, Postgres commit order is the canonical presentation order; provider
sequence and timestamps remain available for diagnosis.

## Evidence provenance

A timeline event uses a provenance union:

```json
{
  "provenance": {
    "source": "native | control_plane | kubernetes",
    "native": {
      "runtime_id": "rt_...",
      "native_process_generation": 2,
      "first_native_seq": 41,
      "last_native_seq": 44,
      "wire_record_ids": ["wr_..."],
      "native_ids": { "turn_id": "...", "item_id": "..." }
    },
    "control_plane": { "command_id": "cmd_..." },
    "kubernetes": { "object_uid": "...", "resource_version": "..." }
  }
}
```

Only the member matching `source` is required. A centrally accepted input or uncertainty marker can
have no runtime or native sequence. One native record may contribute to multiple semantic events;
each projection stores its own `projection_key`, and replay upserts by that deterministic key.

Evidence has two storage tiers:

- **restricted raw**: short-retention encrypted native bytes plus pre-redaction hash;
- **operational**: redacted native payload plus post-redaction hash and common projections.

A record says which tier is available. “Raw” never means reconstructed or redacted content.

## Wire record envelope

```json
{
  "wire_record_id": "wr_...",
  "thread_id": "thr_...",
  "sandbox_id": "sbx_...",
  "runtime_id": "rt_...",
  "runtime_generation": 7,
  "native_process_generation": 2,
  "native_seq": 41,
  "direction": "bridge_to_native | native_to_bridge",
  "observed_at": "2026-08-31T20:14:12.123Z",
  "provider": "claude | codex | direct",
  "native_session_id": "optional",
  "native_turn_id": "optional",
  "native_item_id": "optional",
  "payload_type": "provider-native type or method",
  "payload_operational": {},
  "restricted_raw_ref": "optional",
  "pre_redaction_sha256": "optional",
  "post_redaction_sha256": "...",
  "replay": { "bridge_replayed": false }
}
```

The bridge allocates `native_seq` before appending to its append-only PVC log. Postgres stores the record,
assigns a thread anchor, and acknowledges the highest contiguous sequence for that process
generation. Provider-native ids supplement the sequence but do not replace it.

Unknown payloads are still stored and projected as `provider.event` if they affect the visible
rollout.

## Timeline event envelope

```json
{
  "event_id": "evt_...",
  "projection_key": "projector-version:semantic-key",
  "thread_id": "thr_...",
  "thread_seq": 9001,
  "sandbox_id": "optional",
  "runtime_id": "optional",
  "native_process_generation": 2,
  "turn_id": "optional",
  "input_id": "optional",
  "item_id": "optional",
  "operation_id": "optional",
  "kind": "turn.started",
  "observed_at": "2026-08-31T20:14:12.456Z",
  "projector_version": "...",
  "provenance": { "source": "native", "native": {} },
  "data": {},
  "provider_extensions": {}
}
```

Identifiers that do not apply are omitted. Common clients consume `kind`, common ids, and `data`.
Provider detail and diagnostic views also consume `provider_extensions` and provenance.

## Bridge control and replication stream

The bridge/server stream is an internal orchestration protocol, not the public agent-to-agent
interface. Initial messages are:

- `bridge.hello`: Sandbox and Runtime IDs, runtime generation, bridge/provider versions, native
  process state, native session/turn ids, local-log ranges, and last central acknowledgement;
- `server.reconcile`: accepted generation, desired lifecycle, durable cursors, and replay request;
- `input.offer`: committed input plus expected runtime generation;
- `input.bridge_durable`: input persisted in the append-only bridge log;
- `input.native_admitted`: native admission evidence and ids;
- `wire.append`: ordered batch of wire records;
- `wire.ack`: highest contiguous sequence for one process generation;
- `turn.steer`: target input and native/common turn;
- `turn.interrupt`: target common/native turn;
- `runtime.drain`: stop accepting new work and flush evidence;
- `runtime.shutdown`: terminate the child/process group and report exit;
- `heartbeat`: liveness plus current process/turn snapshot;
- `error`: structured protocol, adapter, storage, or lifecycle failure.

Every command includes `command_id` and `runtime_generation`. A stale generation cannot admit input,
advance dispatch, or append authoritative records. Duplicate messages are idempotent by stable id.
A replacement generation is issued only after the previous workload is confirmed unable to keep
running, normally by observing that its Pod and child process are terminated. Central generation
fencing rejects stale bridge writes; it is not a kill switch and cannot prevent a partitioned
native process from continuing side effects.

## Lifecycle events

### Sandbox lifecycle

- `sandbox.requested`;
- `sandbox.allocating`;
- `sandbox.active`;
- `sandbox.suspending`;
- `sandbox.suspended`;
- `sandbox.resuming`;
- `sandbox.failed`;
- `sandbox.disposing`;
- `sandbox.disposed`.

These describe durable environment lifecycle, not whether a turn is working.

### Runtime and process lifecycle

- `runtime.started`, `runtime.ready`, `runtime.recovering`, `runtime.ended`;
- `native_process.started`, `native_process.initialized`, `native_process.exited`;
- `bridge.connected`, `bridge.disconnected`, `bridge.replayed`;
- `evidence.gap_detected`;
- `recovery.outcome_uncertain`.

### Input lifecycle

- `input.accepted`: committed centrally;
- `input.offered`: sent to the current runtime generation;
- `input.bridge_durable`: persisted in the append-only bridge log;
- `input.native_admitted`: provider evidence says it entered native processing/queueing;
- `input.queued_for_future_turn`;
- `input.cancelled`;
- `input.rejected`;
- `input.outcome_uncertain`.

Each input has `role: initiating | steering`. Claude boundary-queued input and Codex targeted
`turn/steer` can both be steering while retaining different native admission/timing fields.

An accepted input also has an origin envelope:

```json
{
  "origin": {
    "kind": "human | agent | automation | external_event",
    "source_id": "opaque source identity",
    "caused_by": ["optional input/message/event ids"],
    "subscription_id": "optional",
    "received_at": "2026-08-31T20:14:12.123Z"
  }
}
```

For a future Agent-to-Agent tool or GitHub/personal-notification adapter, receipt first commits this
ordinary input. If a Turn is active, provider capability and delivery intent decide whether it is
offered as steering or queued for the next Turn. The provenance envelope remains visible so the
model and UI never misrepresent an automated or Agent-authored delivery as Rai's own words.

### Turn lifecycle

- `turn.started`;
- `turn.working`;
- `turn.interrupt_requested`;
- `turn.interrupted`;
- `turn.completed`;
- `turn.failed`;
- `turn.outcome_uncertain`.

A turn starts with one initiating input and contains zero or more admitted steering inputs. An
interrupt request acknowledgement is not a terminal event.

### Conversation items

- `message.started`, `message.delta`, `message.completed`;
- `reasoning.started`, `reasoning.delta`, `reasoning.completed`;
- `plan.updated`;
- `operation.started`, `operation.output`, `operation.completed`, `operation.failed`;
- `provider.event` for a visible native concept without a stable common mapping.

High-frequency deltas can be coalesced in the operational tier after terminal state, but the event
records retain exact source ranges and reconstruction hashes.

## Common operation model

An operation is visible work performed by the harness during a turn:

```json
{
  "operation_id": "op_...",
  "turn_id": "turn_...",
  "kind": "shell | file.read | file.write | file.patch | search | tool | generic",
  "name": "provider-native display name",
  "status": "pending | running | completed | failed | interrupted | unknown",
  "input": {},
  "output": {},
  "error": null,
  "started_at": "...",
  "completed_at": "...",
  "provider_extensions": {}
}
```

The neutral protocol describes observed operation input/output and lifecycle. It does not define how
an operation is routed or governed.

### `shell`

```json
{
  "kind": "shell",
  "input": { "command": "pytest -q", "cwd": "/workspace/project" },
  "output": { "stdout": "...", "stderr": "...", "exit_code": 1 }
}
```

Claude `Bash` and Codex `commandExecution` map here. Shell output can stream through
`operation.output`; the terminal event carries final exit information.

### File operations

- `file.read`: path/range plus returned content metadata;
- `file.write`: path plus resulting content/digest metadata;
- `file.patch`: one or more path changes, kind, and diff;
- `search`: query, scope, match count, and bounded results.

Claude `Read`, `Write`, `Edit`, `Glob`, and `Grep` map when semantics are clear. Codex
`fileChange` maps to `file.patch`. Unknown or mixed operations remain `tool` or `generic` rather than
claiming false equivalence.

### `tool`

`tool` is the common fallback for a named structured call with observable arguments and result:

```json
{
  "kind": "tool",
  "name": "lookup_issue",
  "input": { "number": 123 },
  "output": { "content": [], "structured": {} },
  "error": null
}
```

The native provider name and payload remain in `provider_extensions`. The v0 protocol does not make
the central server the execution router for these calls.

## Provider mapping

| Common concept        | Claude Code stream/control                                            | Codex app-server                                       |
| --------------------- | --------------------------------------------------------------------- | ------------------------------------------------------ |
| Native session        | emitted Claude session id                                             | `thread.id`                                            |
| Initiating input      | UUID-stamped user frame                                               | `turn/start` with client user-message id               |
| Input admission       | UUID `command_lifecycle` queue/start evidence                         | accepted response plus `turn/started`                  |
| Steering input        | additional UUID user frame observed at a provider boundary            | targeted `turn/steer`                                  |
| Turn bracket          | native work after initiating input through terminal `result`          | `turn/started` through `turn/completed`                |
| Assistant message     | assistant content and partial stream events                           | `agentMessage` item and delta/completion notifications |
| Reasoning             | thinking content/events when exposed                                  | reasoning item and deltas                              |
| Shell operation       | `Bash` tool use/result                                                | `commandExecution`                                     |
| File operation        | `Read`, `Write`, `Edit`, `Glob`, `Grep` where semantics are known     | `fileChange`; other items stay provider-specific       |
| Structured tool call  | named tool-use/result blocks                                          | structured tool-call item where exposed                |
| Interrupt request     | interrupt control request/response                                    | `turn/interrupt` response                              |
| Terminal turn outcome | terminal `result`, correlated to the current Claude execution bracket | `turn/completed` terminal status                       |
| Unknown feature       | original native record                                                | original native notification/item                      |

Claude's terminal `result` can cover an execution bracket containing multiple submitted inputs.
Input admission is therefore derived from UUID lifecycle evidence, not inferred from the result.
An interrupt control response records only that the request was handled; terminal interruption
requires later provider evidence.

## Projection invariants

1. The wire record is stored before native projection.
2. Every native-derived common event cites exact process-generation sequence ranges.
3. Control-plane/Kubernetes events use their own provenance member and can omit native ids.
4. Replaying a native record upserts the same `projection_key`; it does not duplicate semantics.
5. A completed provider item supersedes partial snapshots for final rendering but does not erase
   the source deltas.
6. One native record may produce several events only with deterministic, distinct projection keys.
7. Common status never claims success when provider terminal evidence is absent.
8. Unknown provider records are retained and do not block later records.
9. Provider-native ids are never reused as global ids without provider/runtime scoping.
10. `thread_seq` is immutable once assigned; late replay appears at a new ingestion anchor while its
    original native timestamp/sequence remains visible.

## Client rendering

The default rollout merges common events by `thread_seq` and renders:

- user inputs with initiating/steering admission state;
- assistant messages, reasoning summaries, and plans;
- shell, file, structured-tool, and generic operation cards;
- turn, interrupt, recovery, reconnect, suspension, and uncertainty markers.

The raw-evidence view expands the same anchors. It can show native order within a process generation,
but it does not reorder the common timeline or hide late replay.

Sandbox lifecycle and runtime/turn activity are rendered separately. “Suspended” means Pod absent
with durable environment retained; “working” means a Runtime currently has an active turn.

## Optional A2A projection

The rich common timeline is an internal orchestration and UI model. An optional A2A facade projects
only the opaque agent-to-agent subset:

- private Thread <-> opaque A2A `context_id` through a server-side mapping;
- private delegated Turn <-> opaque A2A `Task` id through a server-side mapping;
- caller/agent content -> A2A `Message`;
- coarse turn lifecycle -> A2A task status updates;
- deliverable outputs and diffs -> A2A artifact updates.

Operation input/output, native provenance, dispatch admission, fencing, and recovery evidence remain
internal by default. Outbound A2A messages, artifacts, task metadata, and status contain no private
Thread/Turn ids or bridge/common-protocol identifiers. A2A is not the harness-neutral control
protocol. See [a2a.md](a2a.md).

## Deferred beyond v0

- Cross-agent discovery/delegation and agent-card semantics.
- Multiple independent provider Threads/Sessions multiplexed through one native process. Codex
  app-server supports multiple threads, but the Claude print-mode profile is not assumed to do so;
  v0 keeps one native session per bridge process.
- A generic interactive-request family beyond ordinary steering input.
- Rich operation taxonomies beyond the initial intersection.
- Cross-thread operation graphs or multi-agent rooms.
- Whether a direct-LLM loop becomes a supported production adapter.
