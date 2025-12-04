local I = import '../../lib.libsonnet';


I.issue(
  expect_caught_from=[
    ['adgn/src/adgn/agent/approvals.py'],
    ['adgn/src/adgn/mcp/policy_gateway/middleware.py'],
    ['adgn/src/adgn/agent/mcp_bridge/servers/agents.py'],
  ],
  rationale=|||
    Lines 63-64 define `ApprovalRequest(BaseModel)` with single field `tool_call: ToolCall`.

    This is a pointless wrapper: no validation, methods, or behavior. All usage sites immediately
    unwrap it to access `.tool_call`. Middleware.py:291-297 wraps `ToolCall` in `ApprovalRequest`,
    passes to `await_decision()`, then immediately unwraps with `req.tool_call` for notify.
    Servers/agents.py:56 extracts `request.tool_call` for `PendingApproval` construction.

    Delete `ApprovalRequest` class and replace with direct `ToolCall` usage throughout:
    - Change `PendingApproval.request: ApprovalRequest` → `tool_call: ToolCall` (line 71)
    - Change `await_decision(call_id, request: ApprovalRequest)` → `tool_call: ToolCall` (line 96)
    - Change `pending() -> dict[str, ApprovalRequest]` → `dict[str, ToolCall]` (line 117)
    - Update middleware.py/servers/agents.py callers to pass `ToolCall` directly

    This eliminates unnecessary indirection and wrap/unwrap overhead.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/approvals.py': [
      [63, 64],   // ApprovalRequest class definition
      [71, 71],   // PendingApproval.request field
      [96, 96],   // await_decision parameter
      [102, 102], // PendingApproval construction with request
      [117, 119], // pending property return type and dict comprehension
    ],
    'adgn/src/adgn/mcp/policy_gateway/middleware.py': [
      [16, 16],   // Import ApprovalRequest
      [291, 293], // Wrapping ToolCall in ApprovalRequest
      [297, 297], // Unwrapping req.tool_call
    ],
    'adgn/src/adgn/agent/mcp_bridge/servers/agents.py': [
      [21, 21],   // Import ApprovalRequest
      [51, 51],   // Function signature with dict[str, ApprovalRequest]
      [56, 56],   // Extracting request.tool_call
      [57, 57],   // TODO comment about ApprovalRequest
    ],
  },
)
