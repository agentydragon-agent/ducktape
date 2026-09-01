# Common harness protocol and timeline vocabulary

Status: **post-capture design target**. Claude Code and Codex are the two required reference
adapters. The common model describes their useful intersection without discarding provider-native
records, but the first native-wire experiments do not implement or depend on this facade. Its queue,
admission, steering, and operation semantics must be revised from captured behavior before becoming
an implementation contract.

This is the intended central product protocol used by the server, bridge, database, and UI. It is
not a replacement for native provider protocols and is deliberately downstream of the raw capture
matrix.

## Design rules

1. **Two native adapters from the start.** A concept is common only when it has a defensible Claude
   and Codex mapping, or when it is explicitly a control-plane concept such as Sandbox lifecycle.
2. **The server receives the native wire.** Every bridge-to-harness and harness-to-bridge frame is
   replicated to the server as an exact ordered record, not merely summarized inside a common
   event.
3. **Projection may be lossy; evidence is not.** Common events are convenient UI/orchestration
   projections. Every projected event cites the exact native records it came from, and unknown
   provider records remain available without a common mapping.
4. **Inputs are independently admitted.** A turn has one initiating input and may have additional
   steering inputs; those inputs do not collapse into one boolean state.
5. **Transport replay is not semantic replay.** Duplicate bridge delivery is deduplicated. Blind
   semantic replay remains a conservative default until native delivery/acknowledgement behavior is
   understood; accepted input must remain durably queued rather than silently discarded.
6. **Lifecycle and activity are separate axes.** Sandbox existence, Runtime and process state, and turn
   activity are not one overloaded status field.
7. **One owner per fact.** PostgreSQL orders product events and control-plane evidence, while
   Kubernetes/Agent Sandbox owns workload lifecycle and native harnesses own native continuity.
   Cross-system observations retain their natural object identities rather than replacing those
   authorities.
8. **Origin is explicit.** A higher layer may send an Agentplane controller an enveloped message
   from a human, Agent, automation, subscription, or external event. Agentplane does not own those
   subscriptions or adapters, and a provider-facing user role does not imply that a human typed it.
9. **Translation follows evidence.** Claude/Codex protocol parsing and native-to-common mapping will
   live inside provider adapters, but the first experiment drivers speak each native protocol
   directly. Shared controller semantics are adopted only after the provider matrix shows that the
   deduplication is real and does not obscure queue or delivery behavior.

## Identities and ordering

The initial stable identifiers are:

- `thread_id`: durable ordered interaction identity for one speaking Agent/harness;
- `sandbox_id`: durable environment record;
- `runner_pod_id`: Kubernetes Pod UID for the concrete runner Pod;
- `runner_process_id`: ordinary process start/exit identity for one bridge/native process instance;
- `harness_thread_id`: opaque resumable Thread identity returned by the active native harness after
  a start (or minted by the optional direct adapter) and passed back unchanged on resume;
- `input_id`: one accepted user input, whether initiating or steering;
- `turn_id`: one common provider execution bracket;
- `item_id`: one common message, reasoning item, or operation;
- `operation_id`: stable lifecycle identity for one operation;
- `thread_seq`: Postgres-assigned durable order for common events and anchored wire records.

`runner_pod_id` and `runner_process_id` use natural Kubernetes/process identities; Agentplane does
not require a separately minted generation token in v0. Adapter-native Claude session, Codex
thread/turn/item, request, and tool ids remain inside the native frames. The server may derive query
indexes from them, but they are not duplicated as authoritative fields in the bridge envelope.
Agent identity, Sandbox identity, Runner Pod identity, and any future authorization principal are
distinct.

The central server can create a product Thread before a harness exists. `harness_thread_id` is absent
until the adapter emits `thread.harness_activated`; it is then stored as an opaque string associated
with the product Thread. For Claude/Codex it is the resumable id returned by the harness, surfaced
unchanged through the neutral facade; callers do not parse it. Common `turn_id`, `item_id`, and
`operation_id` values are likewise minted by the adapter when those concepts become observable; the
adapter privately retains any common-to-native routing map.

The native sequence key is:

```text
(runner_pod_id, runner_process_id, native_seq)
```

It is dense only within one runner process instance. `thread_seq` supplies the total durable order
across control-plane events, process restarts, replacement Pods, and native records. When events
are received concurrently, Postgres commit order is the canonical presentation order; provider
sequence and timestamps remain available for diagnosis.

## Evidence provenance

A timeline event uses a provenance union:

```json
{
  "provenance": {
    "source": "native | control_plane | kubernetes",
    "native": {
      "runner_pod_id": "pod_uid_...",
      "runner_process_id": "process_started_at_...",
      "first_native_seq": 41,
      "last_native_seq": 44,
      "wire_record_ids": ["wr_..."]
    },
    "control_plane": { "command_id": "cmd_..." },
    "kubernetes": { "object_uid": "...", "resource_version": "..." }
  }
}
```

Only the member matching `source` is required. A centrally accepted input or uncertainty marker can
have no runtime or native sequence. One native record may contribute to multiple semantic events;
each projection stores its own `projection_key`, and replay upserts by that deterministic key.

## Wire record envelope

```json
{
  "wire_record_id": "wr_...",
  "thread_id": "thr_...",
  "sandbox_id": "sbx_...",
  "runner_pod_id": "pod_uid_...",
  "runner_process_id": "process_started_at_...",
  "native_seq": 41,
  "direction": "bridge_to_native | native_to_bridge",
  "observed_at": "2026-08-31T20:14:12.123Z",
  "provider": "claude | codex | direct",
  "native_frame": {
    "encoding": "base64",
    "bytes_base64": "eyJ0eXBlIjoiYXNzaXN0YW50In0K",
    "byte_length": 21,
    "sha256": "sha256 of the exact bytes",
    "parsed": { "state": "parsed", "value": { "type": "assistant" } }
  },
  "replay": { "bridge_replayed": false }
}
```

`native_frame.bytes_base64` decodes to the exact bytes read from or written to the native protocol,
including its framing newline when present. It is not redacted, reconstructed, normalized, or
reduced to selected fields. `parsed` is a required non-null diagnostic/indexing wrapper derived from
those bytes; malformed input uses an explicit `not_json` state. Claude `session_id` values and Codex
thread/turn/item/request ids therefore remain available in their original locations without
redundant outer-envelope copies.

The bridge allocates `native_seq` before appending the complete record to its append-only PVC log.
Postgres stores the record, assigns a thread anchor, and acknowledges the highest contiguous
sequence for that runner process. The adapter emits linked common events. The server may parse
native JSON for debug views, derived indexes, and offline reprojection, but normal orchestration does
not implement Claude/Codex translation and the exact bytes remain authoritative.

The database must not collapse provider JSON `null` into SQL `NULL`. Store the exact frame in a
non-null `TEXT`/`BYTEA` column. If parsed JSON is materialized in JSONB, store a non-null wrapper such
as `{"state":"parsed","value":null}`; use a different explicit wrapper for parse failure. Do not use
a nullable JSONB column whose Python `None` encoding can erase the distinction between an absent
database value and a provider-supplied JSON `null`. Ducktape's existing
[`JSONB(none_as_null=True)` precedent](../../../haku/console/database_schema.py) demonstrates the bug to
avoid, but the new implementation should make presence explicit rather than depend on ORM defaults.

For the common facade, omit a member when it is not applicable or not yet known. Use JSON `null` only
when the common schema assigns it an explicit meaning such as “observed no error.” In PostgreSQL,
ordinary absent optional scalars use SQL `NULL`; arbitrary JSON values use a required wrapper or a
separate presence/state column. Tests must round-trip all three cases independently: member absent,
member present with JSON `null`, and member present with a non-null JSON value.

Unknown payloads are still stored and projected as `provider.event` if they affect the visible
Thread timeline.

## Timeline event envelope

```json
{
  "event_id": "evt_...",
  "projection_key": "adapter-version:semantic-key",
  "thread_id": "thr_...",
  "thread_seq": 9001,
  "sandbox_id": "optional",
  "runner_pod_id": "optional",
  "runner_process_id": "optional",
  "turn_id": "optional",
  "input_id": "optional",
  "item_id": "optional",
  "operation_id": "optional",
  "kind": "turn.started",
  "observed_at": "2026-08-31T20:14:12.456Z",
  "adapter_projection_version": "...",
  "provenance": { "source": "native", "native": {} },
  "data": {},
  "provider_debug": {}
}
```

Identifiers that do not apply are omitted. Common clients consume `kind`, common ids, and `data`.
Provider detail and diagnostic views may also consume `provider_debug` and provenance.
`provider_debug` is informational only: common lifecycle, dispatch, retry, recovery, and authorization
logic must not depend on it. The cited native frames remain the source for provider-specific facts.

The adapter emits the common `kind`, common ids, `data`, `provider_debug`, and native-source links.
Postgres adds `event_id`, immutable `thread_seq`, and central ingestion metadata. This preserves one
global Thread order without moving Claude/Codex translation into the server.

## Bridge control and replication stream

The bridge/server stream is an internal orchestration protocol, not the public agent-to-agent
interface. Initial messages are:

- `bridge.hello`: Sandbox and Runner Pod IDs, bridge/provider implementation and
  best-effort resolved harness versions, native process state, local-log ranges, and last central
  acknowledgement;
- `server.reconcile`: desired lifecycle, durable cursors, and replay request;
- `input.offer`: committed input, common delivery intent/target, and expected Runner Pod/process
  identity when one is known;
- `input.cancel`: request dequeue of a common `input_id` that has not been delivered;
- `input.bridge_durable`: input persisted in the append-only bridge log;
- `input.native_admitted`: common admission state plus the exact native wire-record references that
  support it;
- `wire.append`: ordered batch of wire records;
- `event.append`: ordered batch of provider-neutral events already translated by the adapter, each
  linked to its source wire records when applicable;
- `wire.ack`: highest contiguous sequence for one runner process;
- `turn.steer`: target input and common turn; the adapter resolves any provider-native target from
  retained native state;
- `turn.interrupt`: target common turn; the adapter resolves the provider-native request;
- `runner.drain`: stop accepting new work and flush evidence;
- `runner.shutdown`: terminate the child/process group and report exit;
- `heartbeat`: liveness plus current process/turn snapshot;
- `error`: structured protocol, adapter, storage, or lifecycle failure.

Every command includes `command_id` and the natural Runner Pod/process identity when applicable.
Duplicate messages are idempotent by stable id. If observed failure modes require stale-writer
protection, add a lease or connection epoch later; it is not a v0 identity prerequisite and cannot
serve as a kill switch for a partitioned native process.

## Lifecycle events

### Harness Thread activation

- `thread.harness_starting`;
- `thread.harness_activated`: includes the harness-issued opaque `harness_thread_id`;
- `thread.harness_resuming`;
- `thread.harness_resumed`;
- `thread.harness_activation_failed`.

Starting a product Thread does not require a pre-existing native id. Starting the harness lets the
provider mint `harness_thread_id`; resuming later supplies that same opaque id to the common
adapter facade. Native Claude/Codex ids used underneath it remain adapter-owned state.

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

The following is a candidate product lifecycle, not a prerequisite for native-wire capture. In
particular, ownership of pending normal prompts is intentionally unresolved: the orchestrator,
bridge/runner, or native harness may own the operative queue. The capture matrix must show which
queues exist, when a write becomes native admission or delivery, and whether dequeue is supported
before this state machine and the `submit` contract are frozen.

- `input.accepted`: committed centrally;
- `input.offered`: sent to the current Runner Pod/process connection;
- `input.bridge_durable`: persisted in the append-only bridge log;
- `input.adapter_queued`: retained by the adapter but not yet written to the harness;
- `input.native_offered`: its native request/frame was written;
- `input.native_admitted`: provider evidence says it entered native processing or a native queue;
- `input.native_delivered`: provider evidence says it reached an execution/model boundary; emitted
  only when that distinction is observable;
- `input.queued_for_future_turn`;
- `input.dequeue_requested`;
- `input.dequeued`;
- `input.dequeue_unsupported`;
- `input.too_late_to_dequeue`;
- `input.rejected`;
- `input.outcome_uncertain`.

Each input has `delivery_intent: new_turn | steer` and, for steering, a common `target_turn_id`.
The eventual adapter never exposes a native turn id to its caller. The final meaning of `submit`
while active, queue ownership, and dequeue responsibility is selected only after the provider
experiments. `steer` remains distinct from a future-turn prompt, and dequeue remains distinct from
interrupt.

When a higher layer sends an accepted input, it may include an origin envelope; Agentplane does
not manage the subscription or external-event source itself:

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

### Thread items

- `message.started`, `message.delta`, `message.completed`;
- `reasoning.started`, `reasoning.delta`, `reasoning.completed`;
- `plan.updated`;
- `operation.started`, `operation.output`, `operation.completed`, `operation.failed`;
- `provider.event` for a visible native concept without a stable common mapping.

High-frequency common deltas may be coalesced after terminal state, but the exact cited native
frames remain available and ordered.

## Common operation model

An operation is visible work performed by the harness during a turn:

```json
{
  "operation_id": "op_...",
  "turn_id": "turn_...",
  "kind": "shell | file.read | file.change | search | tool | generic",
  "name": "provider-native display name",
  "status": "pending | running | completed | failed | interrupted | unknown",
  "input": {},
  "output": {},
  "error": null,
  "started_at": "...",
  "completed_at": "...",
  "provider_debug": {}
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

Provider-only shell metadata such as Codex `commandActions`, provider item ids, execution-source
labels, or Claude tool-use details may be copied into `provider_debug` for inspection. That field is
not a control surface: dispatch, retry, interruption, success, and recovery decisions use common
fields plus cited native evidence, never provider-debug metadata.

### File operations

- `file.read`: path/range plus returned content metadata when the native record exposes it clearly;
- `file.change`: best-effort paths and broad `created | modified | deleted | unknown` actions;
- `search`: query, scope, match count, and bounded results.

The file-change projection is intentionally allowed to be lossy. Claude `Write`/`Edit` and Codex
`fileChange` can report useful paths or broad actions without forcing their different patch,
approval, and application semantics into one schema. Diffs, provider status, generated patches, and
unknown fields remain in the cited native frames. Claude `Read`, `Glob`, and `Grep` map only when
their semantics are clear; unknown or mixed operations remain `tool` or `generic` rather than
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

The complete native provider name and payload remain in the cited native frames; selected
informational fields may also appear in `provider_debug`. The v0 protocol does not make the central
server the execution router for these calls.

## Provider mapping

| Common concept        | Claude Code stream/control                                            | Codex app-server                                       |
| --------------------- | --------------------------------------------------------------------- | ------------------------------------------------------ |
| Harness Thread id     | adapter exposes emitted Claude session id as opaque common id         | adapter exposes `thread.id` as opaque common id        |
| Initiating input      | UUID-stamped user frame                                               | `turn/start` with client user-message id               |
| Input admission       | UUID `command_lifecycle` queue/start evidence                         | accepted response plus `turn/started`                  |
| Steering input        | additional UUID user frame observed at a provider boundary            | targeted `turn/steer`                                  |
| Turn bracket          | native work after initiating input through terminal `result`          | `turn/started` through `turn/completed`                |
| Assistant message     | assistant content and partial stream events                           | `agentMessage` item and delta/completion notifications |
| Reasoning             | thinking content/events when exposed                                  | reasoning item and deltas                              |
| Shell operation       | `Bash` tool use/result                                                | `commandExecution`                                     |
| File operation        | broad `file.read`/`file.change` projection where useful               | broad `file.change`; exact details stay native         |
| Structured tool call  | named tool-use/result blocks                                          | structured tool-call item where exposed                |
| Interrupt request     | interrupt control request/response                                    | `turn/interrupt` response                              |
| Terminal turn outcome | terminal `result`, correlated to the current Claude execution bracket | `turn/completed` terminal status                       |
| Unknown feature       | original native record                                                | original native notification/item                      |

Claude's terminal `result` can cover an execution bracket containing multiple submitted inputs.
Input admission is therefore derived from UUID lifecycle evidence, not inferred from the result.
An interrupt control response records only that the request was handled; terminal interruption
requires later provider evidence.

## Projection invariants

1. The adapter/bridge durably records the wire record before emitting its linked common projection.
2. Every native-derived common event cites exact runner-process sequence ranges.
3. Control-plane/Kubernetes events use their own provenance member and can omit native provenance.
4. Replaying a native record upserts the same `projection_key`; it does not duplicate semantics.
5. A completed provider item supersedes partial snapshots for final rendering but does not erase
   the source deltas.
6. One native record may produce several events only with deterministic, distinct projection keys.
7. Common status never claims success when provider terminal evidence is absent.
8. Unknown provider records are retained and do not block later records.
9. Provider-native ids stay in native records; any derived query index is non-authoritative and
   scoped by provider and Runner Pod/process.
10. `thread_seq` is immutable once assigned; late replay appears at a new ingestion anchor while its
    original native timestamp/sequence remains visible.

## Client rendering

The default Thread timeline merges common events by `thread_seq` and renders:

- user inputs with initiating/steering admission state;
- assistant messages, reasoning summaries, and plans;
- shell, file, structured-tool, and generic operation cards;
- turn, interrupt, recovery, reconnect, suspension, and uncertainty markers.

The native-frame view expands the same anchors. It can show native order within a runner process
instance, but it does not reorder the common timeline or hide late replay.

Sandbox lifecycle and runtime/turn activity are rendered separately. “Suspended” means Pod absent
with durable environment retained; “working” means a Runtime currently has an active turn.

## Deferred beyond v0

- Cross-agent discovery/delegation and agent-card semantics.
- Multiple product Threads multiplexed through one Runtime/native process. Codex app-server can
  host multiple native threads, but each Agent would still have a distinct product Thread and
  harness Thread. The tested Claude print-mode behavior is not assumed to support equivalent
  multiplexing; v0 keeps one Thread per bridge process.
- A generic interactive-request family beyond ordinary steering input.
- Rich operation taxonomies beyond the initial intersection.
- Cross-thread operation graphs or multi-agent rooms.
- Whether a direct-LLM loop becomes a supported production adapter.
