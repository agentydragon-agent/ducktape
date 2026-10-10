# MCP tasks, progress, and partial output for Actions

## Scope and invariant

An MCP task for `request_action` is a _view of one canonical Action request_, not a
second dispatch queue. The Action Service owns approval, authorization, idempotency,
execution leases, and the final answer. A lost MCP response must be recoverable by the
original caller's idempotency key; a new task request must not execute the Action again.
Keep non-task `request_action`, `get_action_request`, `get_action_result`, and HTTP
clients working throughout the rollout.

Start with task-augmented `request_action` only. Do not enable FastMCP's generic task
support until its task store and dispatch behavior can be backed by Agentplane's durable
Action request and caller authorization; a process-local task would not survive a
reconnect or another replica. Negotiate task support only for requests whose actual
implementation meets the MCP task contract.

## Protocol contract

- A task-augmented `request_action` still requires the usual caller-authored
  `idempotency_key`. Submit through `ActionService.submit` once, then answer with a
  `CreateTaskResult` whose task ID identifies that Action request. If a response is
  lost, recover by idempotency key through the existing read API; never resubmit under
  a different key. Keep access to tasks scoped to the submitting caller, including
  `tasks/get`, `tasks/result`, `tasks/list`, and `tasks/cancel`.
- `tasks/get` reads canonical state and maps `decision_pending`, `allowed`,
  `dispatching`, and `running` to `working`; its status message distinguishes waiting
  for approval from actual execution. Map `succeeded` to `completed`, `denied` and
  `failed` to `failed`, and pre-dispatch withdrawal to `cancelled`. Treat
  `execution_unknown` as a terminal _failed_ task with an explicit unknown-outcome
  diagnostic: it may have run and must not be retried automatically. The task status
  is not the underlying tool result.
- `tasks/result` waits for a terminal outcome and returns the same final content
  blocks, structured content, and error semantics as `get_action_result`, including
  the required related-task metadata. Preserve the backend's result shape; do not
  return a receipt in place of the result. A `tasks/result` transport disconnect
  does not cancel the Action. Read authorization must hold on each request, not only
  when the task was created. Define a documented task/result retention period before
  advertising task support; do not silently expire an in-progress Action.
- `tasks/cancel` calls the existing pre-dispatch `ActionService.cancel`, with its
  authoritative outcome (`cancelled`, `already_cancelled`, `too_late`, or
  `already_finished`). Do not report `cancelled` for `too_late`, or conflate an MCP
  transport cancellation with cancellation of the Action. Decide how to surface
  `too_late` to the MCP caller without falsely claiming success.

## Progress and partial output

- Capture the original request's `_meta.progressToken` for the task lifetime. Emit
  optional `notifications/progress` using _that_ token until terminal state, even
  after the initial `CreateTaskResult`. A progress notification is not a final result.
  Status changes can also use optional `notifications/tasks/status`; clients must
  still be able to read canonical state with `tasks/get`.
- Start with truthful milestone messages (waiting for decision, approved,
  dispatching, running); don't manufacture percentages for approval delays. Add a
  lease-authenticated executor progress callback for Actions that opt in to numeric
  progress, with monotonic values and bounded rate/size. Commit progress before
  waking readers. PostgreSQL NOTIFY remains an invalidation, not durable data.
  Progress reporting must not grant a worker the ability to decide, complete, or
  report progress for another execution.
- Partial _output_ is separate from MCP progress and from the final tool result.
  Provide an opt-in, bounded, append-only sequence of provisional content records,
  readable with an authorized cursor (`request_id`, `after_sequence`). Explicitly
  label it incomplete and retain ordering across replicas. A failed Action can still
  have partial output; it must never be presented as a successful `tasks/result`.
  Apply the same credential/redaction and caller-visibility boundaries as final
  results. An Action without partial-output support returns final output only.
- Extend `ActionUpdates` to wake a reader after committed progress/output changes;
  re-read after subscription to avoid the subscribe/read race already handled by
  `ActionWaiter`. On update-channel loss, fail the live wait clearly while leaving
  the Action and durable cursor recoverable. Avoid unbounded server-side buffering.

## Rollout and tests

1. Add durable task ownership/linkage and protocol handlers; exercise capability
   negotiation, ordinary non-task calls, lost responses, replica/restart recovery,
   caller isolation, expiry, approval/dispatch transitions, and terminal results.
2. Add milestone progress, then opt-in executor progress. Exercise the original
   progress token across the initial response, increasing progress values, and no
   notifications after terminal state or to another caller.
3. Add opt-in cursor-based partial output, with pagination, size/retention limits,
   authorization, reconnects, failure, and racing completion tests.
4. Exercise cancel-vs-dispatch races and `execution_unknown` without duplicate work.

## Deferred extensions

- Cooperatively propagate cancellation into supporting executors after dispatch;
  the current Action cancellation API only withdraws before execution is claimed.
- Bridge upstream MCP _tasks_ (including their progress and final results) into one
  Agentplane Action, preserving the upstream execution-unknown safety boundary. The
  current adapter makes a conventional `call_tool_mcp` call.
- Evaluate task augmentation for dynamically exposed direct tools separately: they
  have auto-approval-only admission, refusal-without-submission, and bounded-wait
  behavior that must not change accidentally.
