local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    ApprovalTimeline.svelte lines 54-61 subscribe to WebSocket endpoint `/ws/approvals?agent_id=...`
    that doesn't exist in backend (app.py has TODO placeholder). Lines 64-87 expect messages with
    type `approval_decision` (tool_call/outcome/reason/timestamp) and `approvals_snapshot` (timeline)
    that backend never sends.

    This creates non-functional feature (component appears to work but receives no updates), silent
    failure (connection fails with no user feedback), misleading UX (suggests live updates work),
    wasted resources (attempts connection that always fails), and incomplete implementation (frontend
    built for missing backend). Lines 92-98 handle errors with console.warn/log only.

    Options: implement backend (add WebSocket endpoint with event subscription), remove WebSocket code
    (replace with polling setInterval), or use MCP subscriptions (subscribe to approval timeline resource
    via MCP client - fits 2-level compositor architecture better). Recommendation: short term remove
    WebSocket or use MCP subscriptions; long term implement endpoint if needed; best use MCP (fits
    architecture). Similar issues: GlobalApprovalsList expects non-existent /api/mcp endpoint.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/web/src/components/ApprovalTimeline.svelte': [
      [54, 61],   // WebSocket subscription to non-existent endpoint
      [92, 98],   // Silent error/close handlers
    ],
    'adgn/src/adgn/agent/server/app.py': [
      [1, 1],     // TODO placeholder for WebSocket routes (actual line varies)
    ],
  },
  expect_caught_from=[
    ['adgn/src/adgn/agent/web/src/components/ApprovalTimeline.svelte'],
    ['adgn/src/adgn/agent/server/app.py'],
  ],
)
