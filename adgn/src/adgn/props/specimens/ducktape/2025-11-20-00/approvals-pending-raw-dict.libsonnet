local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    approvals_pending_global builds approval_data as a raw dict and serializes it with json.dumps().
    Structured data should be handled in Pydantic models - either extend PendingApproval to include
    agent_id, or create a dedicated model for the global mailbox items. This provides validation,
    type safety, and consistent serialization.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/servers/agents.py': [[413, 419]],
  },
)
