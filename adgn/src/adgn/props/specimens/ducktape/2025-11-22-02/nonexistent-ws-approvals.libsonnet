local I = import '../../lib.libsonnet';


I.issue(
  expect_caught_from=[['adgn/src/adgn/agent/web/src/components/ApprovalTimeline.test.ts'], ['adgn/src/adgn/agent/server/app.py']],
  rationale=|||
    ApprovalTimeline tests (lines 486, 512, 538, 601) reference WebSocket endpoint `/ws/approvals` that doesn't exist in the backend.

    Backend evidence (app.py:332): WebSocket routes commented out and never registered (`# register_agents_ws(app)`).

    Code comments in stores_channels.ts indicate `/ws/approvals` was intentionally replaced by MCP resource `resource://agents/{agentId}/approvals/pending`.

    Tests are testing against a non-existent, deprecated API that was replaced by MCP resources. Either update tests to use MCP resources or implement the backend endpoint (uncomment register_agents_ws), but current state is broken.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/web/src/components/ApprovalTimeline.test.ts': [
      486,  // ws://localhost/ws/approvals reference
      512,  // ws://localhost/ws/approvals reference
      538,  // ws://localhost/ws/approvals reference
      601,  // ws://localhost/ws/approvals reference
    ],
    'adgn/src/adgn/agent/server/app.py': [
      332,  // TODO comment about WebSocket routes never registered
    ],
  },
)
