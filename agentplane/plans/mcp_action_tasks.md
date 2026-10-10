# MCP tasks for canonical Actions

## Protocol choice and layering

The desired first wire contract is MCP **2025-11-25 tasks** (`tasks/get`,
`tasks/result`, `tasks/list`, `tasks/cancel`, nested `CreateTaskResult`, and
`_meta.progressToken`). FastMCP 4.0.3 core does not force a task runner: its
`tasks=False` in `mcp_frontend.py` disables the default task declaration.
The separately packaged `fastmcp-tasks` 4.0.3 implements _SEP-2663_, an
extension for the 2026-07-28 protocol era with different wire shapes
(`tasks/get` inlines the result, `tasks/update` replaces `tasks/result`, no
`tasks/list`). That package's Docket queue is **not** a framework requirement.
Do not turn on the packaged extension and claim the 2025-11-25 contract works.

First add a wire-level conformance test for the protocol version we advertise:
capability negotiation, augmented `tools/call`, task reads and final result, all
using actual MCP JSON-RPC over `/mcp`. Implement request interception and task
method handlers against Agentplane's Action Service, using FastMCP's extension
and low-level handler seams where they support that protocol version. If the
pinned MCP SDK cannot advertise/serialize the 2025-11-25 task capability and
result models, make the needed SDK upgrade or narrowly scoped low-level wire
adapter explicit and test it; do not silently negotiate only SEP-2663. A later
SEP-2663 adapter can expose the _same_ Action backing record with its own wire
shapes, without routing execution through Docket. A client must see only the
contract negotiated for its protocol version.

## Where execution actually lives

`request_action` in `mcp_frontend.py` already calls `ActionService.submit`.
That goes through policy evaluation, durable `ActionStore.submit`, and the
existing dispatch loop. `ActionService._dispatch_once` claims one execution;
`_execute_claim` runs the selected `Executor.execute(request, lease)` and
persists the final `ExecutionResult`. The MCP executor invokes an upstream
`call_tool_mcp`; the sandbox executor runs a sandbox Action. A live MCP request
is _not_ the executor worker. Do not enqueue a second tool call or restart a
lost Action merely to create/poll an MCP task.

Make the Action request UUID the MCP task ID (or a stable opaque encoding of
it). An augmented `request_action` must validate its usual arguments, submit
exactly once with its caller-authored idempotency key, then return a task
snapshot. No second task queue, worker, or task-result database is needed:
Action rows hold owner, state and final result. A lost response is recovered
with `get_action_request(idempotency_key=...)` by the original caller; the
existing duplicate-key refusal stays in force, and task lookup never submits.
Keep ordinary (non-augmented) tools and the HTTP Action API unchanged.

The current `/mcp` mount in `api.py` is stateless Streamable HTTP with SSE
responses (`stateless_http=True`, `json_response=False`). A task must survive
that transport, the initial response ending, a replica change, and service
restart. Task reads use the same `CallerTokenVerifier` and canonical
`service.get` / `service.list_requests` owner projection as existing MCP reads;
use not-found for another caller rather than leaking existence. Revalidate
caller credentials on later task requests; do not persist a caller bearer or
backend credentials in task metadata. Task TTL/retention must not cause an
in-progress Action to disappear or invite a second execution: define retention
of completed task views explicitly against Action history retention.

## Map Action states and results

| Canonical Action                    | MCP task    | Meaning                                          |
| ----------------------------------- | ----------- | ------------------------------------------------ |
| `decision_pending`                  | `working`   | Awaiting operator; nothing ran.                  |
| `allowed`, `dispatching`, `running` | `working`   | Approved / claimed / executing, respectively.    |
| `succeeded`                         | `completed` | Result available.                                |
| `denied`, `failed`                  | `failed`    | Readable, distinct diagnostic; denied never ran. |
| `cancelled`                         | `cancelled` | Withdrawn before dispatch.                       |
| `execution_unknown`                 | `failed`    | May have run; do not retry automatically.        |

`tasks/get` maps an authorized `ActionRequestView` into a task snapshot,
including a truthful `statusMessage` and timestamps. `tasks/result` waits for
terminal state using `ActionWaiter` and its subscribe-then-read, cross-replica
`ActionUpdates` invalidation; unlike existing bounded waits, a protocol result
wait may need a transport-long-lived SSE response and reconnect handling. Never
hold one DB connection for the duration. On completion, use the existing
`tool_result` conversion so upstream MCP blocks (images, structured content,
`isError`) and sandbox results keep their shapes. Include the MCP-required
related-task metadata on the response without overwriting backend metadata.
Denied, failed, cancelled, and unknown outcomes must remain distinguishable.
`tasks/list` pages only this caller's Action-backed tasks. Notifications of
status are optional; canonical reads remain authoritative.

`tasks/cancel` delegates to `ActionService.cancel` (and its atomic
`ActionStore.cancel`). Only `cancelled` / `already_cancelled` may produce a
cancelled task. `too_late` means a claim already won; `already_finished` means
inspect the finished result. Translate those outcomes to the chosen protocol's
error/current-state response without asserting the underlying Action stopped.
An SSE disconnect cancels only its waiter, never its Action. The
`execution_unknown` and lease-expiry safeguards remain intact.

## Progress: backend events, not worker heartbeats

There are currently two different signals: durable `ActionEventView` records
carry sequenced _state transitions_, and `ExecutionLease.heartbeat` proves an
executor still owns a claim. A heartbeat is **not** evidence of progress. Start
with milestone messages from state transitions, e.g. waiting for approval,
approved, claimed, and running, without invented percentages.

For real progress, add a bounded, sequenced Action update table and store API
(for instance, `action_execution_update` keyed by request ID + sequence with
kind, time, safe message, and optional increasing progress/total). An executor
may append updates only through a reporter bound to the current
`executor_id + lease_token`, with the same ownership checks as heartbeat and
finish. This prevents a stale or foreign worker publishing progress. Commit the
update before a PostgreSQL NOTIFY wakeup; readers page durable updates by
cursor, re-reading after subscription as `ActionWaiter` does today. Keep
progress and event cursors distinct unless they are unified transactionally.
Enforce monotonic numeric progress, rate/size bounds, and no writes after a
terminal execution. Do not treat updates as authority to approve, complete,
or retry execution.

Capture `_meta.progressToken` on the _original augmented request_. Where an
MCP transport can carry notifications for that task, send optional
`notifications/progress` with that same token throughout its lifetime, stopping
at terminal state. The existing stateless HTTP mount cannot be assumed to keep
an unsolicited notification channel alive after an immediate task-creation
response: test notification delivery over real Streamable HTTP/SSE, and do not
promise pushes across a disconnected client or arbitrary replicas. Durable
`tasks/get` status plus a cursor-based update read are the reconnect fallback;
use a task `statusMessage` for the latest safe milestone. Do not fabricate a
new progress token on polling calls. Test client disconnects and absent tokens.

## Partial output: opt-in, provisional, not `tasks/result`

Use the same lease-checked append seam for an Action that explicitly opts in
to partial output, but give partial content its own typed update kind, ordered
cursor, bounded payload and retention. Add an authorized `get_action_updates`
read tool/API accepting `request_id` and `after_sequence` (and optionally a
bounded wait). It must never turn an intermediate block into a successful
`tasks/result`; final result remains written only by `finish_execution`.
A failed or unknown Action may have partial output. Apply the normal caller
visibility and backend-output security policy; avoid logging payloads or
including them in public status notifications. Actions without an output
producer simply return no partial output.

For the sandbox executor, report only milestones at the `SandboxExecutor`
boundary initially: the underlying exec API currently returns an `ExecResult`
at completion, not a safe general-purpose incremental content stream. Add
streaming only for specific sandbox Actions whose backend can provide it. For
the MCP executor, use the upstream client's supported progress callback for
progress messages when available; upstream tasks and partial-result streaming
require separate interoperability handling. Neither adapter should claim
partial output support just because an Action takes a long time.

## Rollout and tests

1. Prove the 2025-11-25 wire contract on the actual `/mcp` transport; implement
   durable Action-backed create/get/result/list/cancel and update tool
   descriptions. Test authorization per read, idempotency-loss recovery,
   ordinary calls, multi-replica/restart reads, decision wait, denial, backend
   error results, unknown outcome, expiry, cancellation races and disconnects.
2. Add state-derived status messages and durable lease-checked executor update
   records. Test race-free subscribe/read, cross-replica delivery, monotonicity,
   stale lease refusal, backpressure and terminal write rejection.
3. Add progress-token notification bridging where the transport permits it;
   test the original token, post-creation lifetime and reconnect fallback.
4. Expose opt-in partial output with cursored reads, size limits and explicit
   provisional labeling. Test final-result isolation, failure and absence of
   opt-in output. Validate with the repository's remote Bazel tests and
   real MCP HTTP integration tests before enabling the capability.

## Deferred follow-ups

- Propagate cooperative cancellation after dispatch to executors that declare
  support. For now, `tasks/cancel` can only withdraw before dispatch; it must
  not report a claimed Action as cancelled.
- Proxy an upstream MCP _task_ through a single Agentplane Action, preserving
  its progress/results and the current execution-unknown safety boundary.
  The existing MCP adapter uses a conventional `call_tool_mcp`.
- Task-augment dynamically exposed direct tools after working out their
  auto-approval-only refusal path and bounded-wait behavior. The first
  implementation only augments `request_action`.
