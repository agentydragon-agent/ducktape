local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    approvals_pending_global builds URIs and JSON by accessing approval.call_id, approval.tool,
    and approval.args, but PendingApproval only exposes tool_call (a ToolCall object) and timestamp.
    The code raises AttributeError on every invocation because these attributes don't exist at the
    PendingApproval level - they need to be accessed via approval.tool_call.call_id,
    approval.tool_call.name, and approval.tool_call.args_json respectively.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/servers/agents.py': [[400, 422]],
  },
)
