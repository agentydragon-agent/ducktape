# MCP tasks backed by Agentplane Actions

## Choice of protocol and execution engine

Target the MCP tasks protocol FastMCP 4.0.3 actually supports:
`io.modelcontextprotocol/tasks` (SEP-2663, 2026-07-28 era). This means a
negotiated extension, an immediately returned flat `CreateTaskResult`,
`tasks/get` with the final result inlined, `tasks/update` for input-required
tasks, and `tasks/cancel`. Do **not** implement the obsolete separate
`tasks/result` / `tasks/list` flow or patch the SDK to advertise it. The
initial feature targets task-augmented `request_action` only; continue to
accept ordinary, synchronous calls.

FastMCP provides `ServerExtension`, `MethodBinding`, and
`intercept_tool_call` for custom task backends. Its optional
`fastmcp-tasks` package uses Docket, with memory or Redis storage, to queue
and rerun ordinary tools. Agentplane has its own durable Action submission,
policy decision, execution claim, and final-result storage, so write an
Agentplane-specific extension instead of adding a second worker/queue. Use
FastMCP's extension interface and negotiated capability; this is not a
change to the MCP SDK or a fork of the Docket extension.

Start with a wire-level acceptance test against the existing `/mcp` endpoint
that opts into the tasks extension, checks a task-augmented `tools/call`,
`tasks/get` throughout its lifecycle (including inlined final result),
`tasks/cancel`, and an unchanged non-task call. Also test an unsupported
`tasks/update` on an Action-backed task produces a clear error rather than
inventing an `input_required` state. Advertise the extension only after
its handlers are registered and this test passes.

## Execution and durable identity

`request_action` already calls `ActionService.submit`, which evaluates
policy and persists one `ActionRequestRow`. The service dispatch loop claims
one `ExecutionRow`; `_execute_claim` runs the selected `Executor.execute`
and stores the final `ExecutionResult`. MCP and sandbox executors keep their
existing ownership and lease behavior. A task lookup must never call an
executor or resubmit an Action.

Intercept only an opted-in task call to `request_action`; validate its
normal action arguments, policy admission, and idempotency key, and submit
through the existing service path once. Use the request UUID as the task ID.
Task-augmented calls must use default `respond_with=result` and zero wait;
reject incompatible options before submission. Leave normal tool calls
alone. Preserve the existing recovery contract: after a lost create response,
read by the same caller's idempotency key; never submit under a new one.
Persist just the metadata not derivable from the Action (task creation/TTL,
and a terminal state/result latch). Do not persist caller tokens, backend
credentials, or process-local task handles. Cross-replica and restarted
servers read the same Action and task rows. Task IDs alone grant no access:
authenticate and authorize each task method with the existing caller
verification and `ActionService.get`/`list_requests` owner projection. Return
not-found for another caller.

## Map results and cancellation honestly

| Action state                        | Task state              | Response                                                          |
| ----------------------------------- | ----------------------- | ----------------------------------------------------------------- |
| `decision_pending`                  | `working`               | Awaiting approval; nothing ran.                                   |
| `allowed`, `dispatching`, `running` | `working`               | Approved, claimed, executing.                                     |
| `succeeded`                         | `completed` or `failed` | Inline the final tool result; `isError=true` means a failed task. |
| `denied`, `failed`                  | `failed`                | Distinct diagnostic/error.                                        |
| `cancelled`                         | `cancelled`             | Withdrawn before dispatch.                                        |
| `execution_unknown`                 | `failed`                | May have run; no automatic retry.                                 |

SEP-2663 `tasks/get` includes the completed result, rather than requiring a
second `tasks/result` call. Adapt the existing `tool_result` conversion so
upstream MCP content (including images, structured content and `isError`)
and sandbox results keep their shapes. An upstream tool's `isError=true`
currently still counts as a successfully executed Action, but it must map
to `failed` _task status_ without losing the original tool result.

MCP task statuses are terminal once `completed`/`failed`/`cancelled`. An
`execution_unknown` Action can subsequently be reconciled by the owner or
backend authority. Latch the first terminal task status and final
result/diagnostic durably; subsequent canonical Action reads may show newer
truth, but a completed MCP task cannot revert to `working` or change its
published outcome. Bound task retention without expiring an active Action.

`tasks/cancel` must use `ActionService.cancel`. Only its `cancelled` and
`already_cancelled` outcomes warrant a cancelled task; `too_late` must
return a clear cannot-cancel error because the current executor cannot be
stopped. `already_finished` requires inspecting the existing outcome.
A disconnect from `/mcp` ends only a waiter, never an Action. An
uncertain outcome must not be replayed. Leave cooperative cancellation
for executor implementations as a follow-up.

## Backend progress and partial output

Action events currently store sequenced state transitions and wake all
replicas via PostgreSQL NOTIFY. `ExecutionLease.heartbeat` only proves
ownership; it does **not** mean the backend advanced. Start with truthful
status messages derived from those state changes, without made-up numeric
percentages. `tasks/get` is the durable reconnect path.

For actual progress, add a bounded, append-only Action execution update
stream with sequence, time, type, safe message, and optional increasing
progress/total. Extend the executor lease/reporter seam so only the
currently owning `executor_id + lease_token` can append an update. Reject
stale owners and terminal updates; commit data before NOTIFY and page by
cursor. Readers subscribe then reread as `ActionWaiter` does today to avoid
missing a racing commit. Apply rate/size limits and never let progress
reports decide, finish, or re-execute an Action.

Progress notifications are optional: `/mcp` currently uses _stateless_
Streamable HTTP with a fresh transport for each request, so a quick
create response cannot deliver unsolicited notifications after it closes.
If a client holds open a streaming request and the transport supports
out-of-band progress, test that path against actual MCP JSON-RPC; do not
promise push after disconnect or across an arbitrary replica. In any case,
`tasks/get.statusMessage` and a caller-authorized `get_action_updates`
read tool with `after_sequence` provide reliable progress on reconnect.
Do not confuse the old `_meta.progressToken` examples with requirements
for SEP-2663; follow the negotiated version's wire contract in tests.

Partial output is a **separate, opt-in update type** with bounded content
and a durable cursor. Label it provisional; a failed Action can have
partial output, and it never becomes an inlined successful final result
until `finish_execution` writes the final answer. The sandbox adapter
currently returns `ExecResult` at completion; it should report milestones
first and only advertise streaming for actions whose backend actually
supports it. The MCP adapter currently calls an upstream tool normally;
forward supported upstream progress only where safe. Leave upstream MCP
task proxying as a follow-up, including its cancellation and
execution-unknown handling.

## Implementation checkpoints

1. Build the Agentplane-specific FastMCP task extension against
   `ActionService`, not Docket, and test capability negotiation, create,
   get-with-inline-result, cancel, task scoping, ordinary calls, idempotency
   loss recovery, denial and execution-unknown over `/mcp`.
2. Add the terminal snapshot, reconciling-unknown case, `isError` mapping,
   retention and replica/restart tests before enabling the capability.
3. Add lease-checked progress and cursor reads, then opt-in partial output
   with authorization, bounds, ordering and final-result isolation tests.
4. Test live transport behavior and add optional notifications only when
   proven, keeping durable reads as the baseline. Keep TODOs in code for
   post-dispatch cooperative cancellation, upstream task proxying, and
   direct-tool tasks; they require separate semantics.

## Preflight findings

The pinned SDK and FastMCP provide the 2026-era extension seams needed;
no SDK fork or Docket deployment is a prerequisite. The existing
`mcp_frontend.py` has `tasks=False` and the direct-tool provider returns no
tasks; neither currently implements the Action-backed extension.

Pre-commit for plan edits passed. A baseline remote
`bbr test //agentplane/action_service:test_mcp_frontend` could not run:
without a BuildBuddy key the client refused, and passing the egress
placeholder as `BUILDBUDDY_API_KEY` caused remote Bazel to reject the
literal. The sandbox proxy cannot provision that key inside a remote
runner. Do not repeat that approach; validate through PR CI or an
approved runner configuration. This preflight did not validate runtime
tests.
