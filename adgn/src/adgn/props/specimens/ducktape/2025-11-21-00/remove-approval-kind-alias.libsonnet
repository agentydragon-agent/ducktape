local I = import '../../lib.libsonnet';


I.issue(
  expect_caught_from=[
    ['adgn/src/adgn/agent/server/state.py'],
    ['adgn/src/adgn/agent/mcp_bridge/servers/agents.py'],
  ],
  rationale=|||
    Line 41 defines `ApprovalKind = UserApprovalDecision` type alias. Used in state.py:73,
    state.py:130, servers/agents.py:30, servers/agents.py:609.

    Alias adds no semantic value: doesn't convey anything different from UserApprovalDecision,
    adds indirection (readers must look up), inconsistent naming (actual type has different
    name), not a true abstraction (1:1 with no behavior), import clutter.

    Fix: remove alias (line 41), replace all usages with `UserApprovalDecision` directly.
    Benefits: one canonical name, clearer code, less cognitive overhead, easier to search/refactor.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/state.py': [
      [41, 41],   // ApprovalKind type alias definition - delete
      [73, 73],   // ToolItem.decision field - replace with UserApprovalDecision
      [130, 130], // update_tool_decision parameter - replace with UserApprovalDecision
    ],
    'adgn/src/adgn/agent/mcp_bridge/servers/agents.py': [
      [30, 30],   // Import statement - replace ApprovalKind with UserApprovalDecision
      [609, 609], // Parameter type - replace ApprovalKind with UserApprovalDecision
    ],
  },
)
