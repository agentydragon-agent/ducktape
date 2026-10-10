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

### Preflight: the pinned SDK does not yet serve legacy tasks

The repository pins `fastmcp-slim==4.0.3`, `mcp[cli]==2.2.0`, and
`mcp-types==2.2.0` (`requirements_bazel.txt`). Inspecting those versions:
`mcp-types` has **generated** 2025-11-25 task models, including a nested
`CreateTaskResult` and `ServerCapabilities.tasks`, but its runtime method
maps **deliberately omit** the 2025-11-25 `tasks/*` requests and task-status
notification. The SDK's `ServerRunner` validates known spec methods against
those maps before handler lookup, and validates a `tools/call` response
against the ordinary tool result shape. Its handshake capability builder
uses the version-free capability model (with extensions for modern versions),
not the generated 2025-11-25 `tasks` field. Consequently, simply registering
FastMCP handlers or enabling `tasks=True` cannot advertise or deliver the
2025-11-25 contract. `ServerExtension` supports custom request methods and
interception but only advertises `capabilities.extensions`, appropriate to
SEP-2663, not legacy `capabilities.tasks`.

**First code milestone:** make the SDK's optional 2025-11-25 task capability,
method dispatch, result variants and task-status notification work (prefer a
small upstream-compatible change to the SDK dependency and its wire tests
over ad-hoc HTTP interception). Upgrade the pinned SDK if an upstream release
supplies this; otherwise keep the compatibility change explicitly isolated,
covered by integration tests, and tracked for upstreaming. Then implement an
Agentplane-specific FastMCP request interceptor and handlers that use canonical
Actions rather than Docket. Prove capability negotiation, augmented
`tools/call`, `tasks/get`/`list`/`result`/`cancel`, and unchanged non-task
calls over the actual `/mcp` mount **before advertising** task support. A
later SEP-2663 adapter can expose the same Action-backed task through that
protocol's wire shapes. A client only sees the contract negotiated for its
protocol version.

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
it). For task augmentation, require `respond_with=result` and the default
zero wait; reject incompatible receipt/wait options _before submission_, or
persist their exact result shape for `tasks/result`. An augmented
`request_action` must validate its usual arguments, submit exactly once
with its caller-authored idempotency key, then return a task snapshot. No second task queue or worker is needed:
Action rows hold owner, state and final result. Persist only the task-specific metadata that cannot be
reconstructed from an Action (e.g. creation protocol/version, expiry policy,
terminal-status latch and safe final diagnostic); never store caller bearer
credentials in it. A lost response is recovered with `get_action_request(idempotency_key=...)` by the original caller; the
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

| Canonical Action                    | MCP task                | Meaning                                                                        |
| ----------------------------------- | ----------------------- | ------------------------------------------------------------------------------ |
| `decision_pending`                  | `working`               | Awaiting operator; nothing ran.                                                |
| `allowed`, `dispatching`, `running` | `working`               | Approved / claimed / executing, respectively.                                  |
| `succeeded`                         | `completed` or `failed` | `CallToolResult.isError=true` requires `failed`; preserve the original result. |
| `denied`, `failed`                  | `failed`                | Readable, distinct diagnostic; denied never ran.                               |
| `cancelled`                         | `cancelled`             | Withdrawn before dispatch.                                                     |
| `execution_unknown`                 | `failed`                | May have run; latch the terminal task snapshot; do not retry.                  |

`tasks/get` maps an authorized `ActionRequestView` into a task snapshot,
including a truthful `statusMessage` and timestamps. **Do not map terminal
states from the current Action state alone:** an `execution_unknown` Action
can later be reconciled by a late lease-authenticated completion or authority
lookup. MCP tasks cannot leave a terminal state. Persist a terminal task
snapshot on first terminal transition (including unknown) and preserve its
result/diagnostic across later Action reconciliation; direct Action reads may
show the newer canonical truth. Similarly, inspect upstream MCP
`CallToolResult.isError`: Action execution can be `succeeded` when the
underlying tool returned an error, but task status must be `failed` while
`tasks/result` still returns that tool's original error result.
`tasks/result` waits for
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
at terminal state. The stateless HTTP manager creates a fresh transport
for every request with no standalone GET stream. Once the task-creation POST returns, that transport
is gone; it **cannot** send later unsolicited notifications over the initial
request. For live progress, provide a deliberately open SSE response (e.g. an
in-flight `tasks/result` wait with a subscribed update reader) and verify the
2025-11-25 progress-token rule and JSON-RPC notification routing on real
Streamable HTTP. Do not claim background push after that stream closes. If
the SDK cannot send the original token on the later stream, either add that
support at the transport layer or restrict live progress to an open
original-request stream and expose later updates as durable reads; test both
cases. Durable `tasks/get` status plus a cursor-based update read are the reconnect fallback;
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

1. Close the pinned SDK method-map/capability/result gap above; prove the
   2025-11-25 contract on actual `/mcp`. Then implement
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

## Validation preflight (2026-10-10)

`pre-commit` for the design and TODO edits passed. A baseline
`bbr test //agentplane/action_service:test_mcp_frontend` first found no
BuildBuddy API key. A second attempt with the egress placeholder in
`BUILDBUDDY_API_KEY` reached a BuildBuddy remote runner but its Bazel step
rejected that literal as an invalid key: proxy substitution on the sandbox's
outbound request does not provision a key _inside_ the remote runner. Do not
repeat that credential pattern or copy a real key into the repository; use
PR CI or an authorized runner configuration that provisions the key through
the approved route. No runtime tests were validated by this preflight.
