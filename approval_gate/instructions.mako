<%doc>
Mako template for the MCP server instructions returned during initialization.

Template variables:
  backend_instructions: str | None  — instructions from the backend MCP server
  public_base_url: str               — base URL for approval action links
</%doc>
# Approval Gate

This server **approval-wraps** calls to a privileged backend MCP server.

## How it works

When you call any tool here, the call is **queued for operator approval** and returns
immediately with an `action_id`. Your call is **not executed yet**.

Share the approval URL `${public_base_url}/actions/<action_id>` with the user so they
can approve or reject the action.

Once the operator approves it, the call is forwarded to the backend server and the
result is recorded. If the OpenClaw plugin is active, the outcome will be **injected
into your session** automatically; otherwise, poll or subscribe to the action resource.

## Tool schema additions

Every tool has two extra fields beyond the backend's original schema:

- `justification` (required `string`): Explain **why** you want to run this action.
  This is shown to the operator to help them decide. Be specific.
- `session_key` (optional `string`): Your session key for result notifications.
  This is injected automatically by the OpenClaw plugin — do not set it manually.

## Response format

Every tool call returns immediately with `{"action_id": "..."}`.

Auto-denied actions return a tool error with the denial reason instead.

## Checking action status

Read the action resource `resource://actions/{action_id}` to get the current state.

The resource returns the full `Action` JSON including `state.status` which is one of:
`pending`, `executing`, `done`, `rejected`, `withdrawn`.

For `done` actions, `state.outcome.content` holds the backend result and
`state.outcome.isError` indicates whether the backend reported an error.

## Subscribing to updates

Subscribe to `resource://actions/{action_id}` to receive `ResourceUpdated`
notifications whenever the action state changes. Unsubscribe once the action
reaches a terminal state (`done`, `rejected`, or `withdrawn`).
% if backend_instructions:

---

## Backend server instructions

${backend_instructions}
% endif
