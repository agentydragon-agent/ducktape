# Implementation reuse and prior art

Status: **proposal evidence**. This document identifies code and behavioral patterns worth reusing
without outsourcing the Harness Control Plane's durability or recovery contract.

## Evaluation rules

A reference is evaluated on four separate axes:

1. **protocol fidelity**: does it own the native structured Claude or Codex wire rather than a PTY;
2. **lifecycle coverage**: does it supervise processes, preserve sessions, and handle shutdown;
3. **recovery semantics**: does it prove admission, fence stale writers, persist evidence, and
   reconcile uncertain outcomes;
4. **reuse rights**: can code be copied or modified for this product under its pinned license.

Passing one axis does not imply the others. A useful parser or test fixture is not automatically a
safe continuity authority.

## Pinned references

| Reference                                                                                                                       | Pin                                                 | License                                    | Recommended role                                       |
| ------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------- | ------------------------------------------ | ------------------------------------------------------ |
| Ducktape Claude and Codex runners                                                                                               | This PR's repository revision                       | Repository license                         | Primary local implementation base                      |
| [`plotarmordev/claude-pool`](https://github.com/plotarmordev/claude-pool/tree/05754a3a3e4fe5ccc1226de29cf295bcb4746e27)         | `05754a3a3e4fe5ccc1226de29cf295bcb4746e27`          | MIT                                        | Claude process-supervision and test patterns           |
| [`openai/symphony`](https://github.com/openai/symphony/tree/8001b52e3062495a16e520e4ceaf8f9de868c4d0)                           | `8001b52e3062495a16e520e4ceaf8f9de868c4d0`          | Apache-2.0                                 | Small Codex handshake and compatibility reference      |
| [`backnotprop/orchestrator`](https://github.com/backnotprop/orchestrator/tree/583acf4b469b91131f96ae2136797749c788b4c7)         | `583acf4b469b91131f96ae2136797749c788b4c7`          | BSL 1.1; Apache-2.0 change date 2029-07-09 | Behavioral prior art only unless licensing is reviewed |
| [`backnotprop/plannotator`](https://github.com/backnotprop/plannotator/tree/9f9ee275294a978d8c46cafc8eace96eb04dd6d3)           | `9f9ee275294a978d8c46cafc8eace96eb04dd6d3`          | MIT OR Apache-2.0                          | Permissive TypeScript Codex parser/provider reference  |
| [Kubernetes SIGs Agent Sandbox](https://github.com/kubernetes-sigs/agent-sandbox/tree/3ea199b8b910f8e838a6000796c29536d592fbdd) | v0.5.5 / `3ea199b8b910f8e838a6000796c29536d592fbdd` | Apache-2.0                                 | First workload lifecycle backend                       |
| [`kagent-dev/kagent`](https://github.com/kagent-dev/kagent/tree/8905d1ca417e4094e6c6fc55a045dd6842d58ec9)                       | `8905d1ca417e4094e6c6fc55a045dd6842d58ec9`          | Apache-2.0                                 | Durable-instance and runtime-reconciliation prior art  |

Pins are evidence anchors, not automatic vendoring decisions. Provider and controller behavior must
still be reprobed against the exact production profile.

## Reuse the existing Ducktape adapters first

The nearest implementation is already in this repository:

- [`haku/cli_protocol`](../../haku/cli_protocol/) owns Claude stream/control framing and probes;
- [`haku/runner/claude/harness.py`](../../haku/runner/claude/harness.py) launches and reads Claude;
- [`haku/runner/claude/projection.py`](../../haku/runner/claude/projection.py) projects native frames;
- [`haku/runner/codex/protocol.py`](../../haku/runner/codex/protocol.py) models Codex app-server
  messages;
- [`haku/runner/codex/harness.py`](../../haku/runner/codex/harness.py) owns the current app-server
  subprocess;
- [`haku/runner/codex/projection.py`](../../haku/runner/codex/projection.py) and
  [`neutral_operations.py`](../../haku/runner/neutral_operations.py) provide the current neutral
  projection seam.

The first bridge slice should extract or wrap these seams rather than introduce independent provider
clients. External projects supply missing tests and lifecycle patterns; they do not replace the
repository's already pinned behavior.

## Claude: `plotarmordev/claude-pool`

The default backend starts one long-lived subprocess with:

```text
claude -p --input-format stream-json --output-format stream-json --verbose
```

It owns dedicated stdin/stdout/stderr pipes, continuously drains stderr, uses a separate POSIX
process group, tolerates malformed or unknown NDJSON records, and keeps a checked-out process alive
across multiple turns. Its fake Claude executable and frozen stream-JSON fixtures exercise
persistent session identity, large records, malformed input, timeout, cancellation, process-tree
cleanup, replenishment, and shutdown races.

The protocol notes were captured against Claude Code `2.1.175`, not the proposed workspace image's
direct `2.1.198` package pin. It is a small alpha project, and its ordinary CI does not run the real
Claude binary.

### Borrow directly, retaining the MIT notice

- subprocess and whole-process-group supervision;
- independent stderr draining to prevent pipe blockage;
- configurable NDJSON line limits and bounded diagnostic tails;
- typed timeout, crash, oversized-record, and broken-pipe diagnostics;
- fake CLI, isolated synthetic native fixtures, and lifecycle race scenarios.

### Adapt substantially

- split its coupled `write prompt -> read until result` method into independent reader and
  correlated writer/router tasks;
- preserve every native record instead of discarding non-terminal frames;
- add exact initialization, input UUIDs, control-response routing, interrupt, mid-turn steering,
  bridge-log acknowledgements, runtime fencing, and native resume;
- make waiting/backpressure bounded and durable rather than an in-memory lock or semaphore.

### Do not copy

- automatic retry of the same prompt after a warm worker crashes: without provider-admission
  evidence this is blind semantic replay and may duplicate side effects;
- process-lifetime `Session` continuity as a claim of crash, daemon-restart, or Pod-replacement
  recovery;
- the Unix-socket daemon's positional, request-ID-free NDJSON protocol;
- its optional PTY/TUI backend as a production correctness path.

## Codex references

### Symphony: small compatibility reference

[`app_server.ex`](https://github.com/openai/symphony/blob/8001b52e3062495a16e520e4ceaf8f9de868c4d0/elixir/lib/symphony_elixir/codex/app_server.ex)
shows a compact Apache-2.0 implementation of:

- app-server launch through local or SSH stdio;
- `initialize`, `initialized`, `thread/start`, and `turn/start`;
- stream-driven inactivity timeouts and `turn/completed` settlement;
- partial-line and malformed-output handling;
- server requests for approvals, user input, and dynamic tools;
- path-safety and process-exit handling.

Its
[`app_server_test.exs`](https://github.com/openai/symphony/blob/8001b52e3062495a16e520e4ceaf8f9de868c4d0/elixir/test/symphony_elixir/app_server_test.exs)
is useful for handshake, timeout, malformed-record, blocker, and dynamic-tool compatibility cases.

Do not adopt its fixed request IDs or sequential response waiter. It does not provide general
out-of-order correlation, resume, steering, interrupt, reconnect, or durable recovery.

### `backnotprop/orchestrator`: behavioral prior art, not a vendoring source

This is the richest inspected Codex app-server design. Useful patterns include:

- concurrent JSON-RPC request routing with monotonically allocated IDs;
- per-request timeouts, server-request handlers, parse/protocol errors, and bounded stderr;
- method/thread/turn notification filters with bounded early-notification buffering;
- `thread/start`, `thread/resume`, `thread/read`, `turn/start`, `turn/steer`, and
  `turn/interrupt`;
- a shared Unix-socket app-server with startup locking, health checks, atomic PID/endpoint metadata,
  stale-socket replacement, and PID start-time ownership checks;
- detached operation monitoring that reconnects, resumes the thread, and reconciles through
  `thread/read` after an original subscriber disappears;
- strong transport, controller race, active-turn steering, resume, and detached-monitor tests.

These behaviors should inform clean-room implementation and tests. BSL 1.1 hosted-service terms
require explicit license review before code reuse, and the architecture remains weaker than the
selected control-plane contract:

- no runtime-generation fencing;
- no bridge log and replay cursor;
- no centrally committed `accepted -> offered -> bridge_durable -> native_admitted -> terminal`
  input lifecycle;
- no dense native-record sequence anchored into one PostgreSQL timeline;
- no exact replay/deduplication contract across replacement runtimes.

One semantic mismatch must be rejected: an interrupt request must not immediately fabricate a
terminal cancelled state. The control plane waits for native terminal evidence or records an
uncertain outcome.

### Plannotator: permissive parser/provider reference

Plannotator's
[`codex-app-server.ts`](https://github.com/backnotprop/plannotator/blob/9f9ee275294a978d8c46cafc8eace96eb04dd6d3/packages/ai/providers/codex-app-server.ts)
is an actively maintained, permissively licensed TypeScript implementation with correlated request
IDs, concurrent response handling, server-request support, stale-waiter cleanup, thread resume,
interrupt, process-group shutdown, and protocol cleanup.

It is an Ask-AI provider, not a persistent orchestration bridge. It has no `turn/steer`, notification
subscriptions, reconnect reconciliation, bridge durability, or replacement-runtime fencing. Borrow
small transport/parser utilities and tests where they fit; do not make its one-operation provider
lifecycle the control-plane model.

## Kubernetes lifecycle prior art

Agent Sandbox v0.5.5 should be reused as the first provisioning backend rather than recreating a
Sandbox/Pod/PVC controller. The bridge still owns provider process supervision and evidence; the
central service still owns Thread identity and accepted input.

kagent demonstrates two useful design directions without supplying a stable CRD to adopt:

- the older `SandboxAgent` CRD moved between Agent Sandbox and Agent Substrate backends and is being
  retired;
- current `AgentInstance` stores durable logical instances, tasks, events, and exact snapshot
  identities in SQL while reconciling suspendable runtime actors underneath.

Borrow the database-backed logical-instance pattern, explicit suspend/resume operations, immutable
runtime-template revisions, and status-condition vocabulary. Do not equate actor snapshots with
native Claude/Codex process hibernation, and do not move Thread authority into Kubernetes CR
status.

## Bridge-owned contract

No inspected reference provides the full selected contract. `harness-bridge` and the central service
must still own:

- exact versioned initialization and compatibility profiles;
- stable input IDs and multiple admission-evidence levels;
- runtime and native-process-generation fencing;
- complete native evidence with direction, local sequence, hashes, and retention tier;
- simple append-only local bridge log plus central acknowledgements and reconnect cursors;
- conservative reconciliation after child, bridge, connection, Pod, or storage loss;
- explicit uncertain outcomes instead of blind semantic replay or fabricated cancellation;
- one PostgreSQL-ordered private timeline across replacement runtimes.

External code is accepted only behind those invariants and the experiments in
[`experiments.md`](experiments.md).
