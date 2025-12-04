local I = import '../../lib.libsonnet';


I.issue(
  expect_caught_from=[
    ['adgn/src/adgn/mcp/_shared/constants.py'],
    ['adgn/src/adgn/agent/mcp_bridge/resources.py'],
    ['adgn/src/adgn/agent/approvals.py'],
    ['adgn/src/adgn/agent/mcp_bridge/servers/agents.py'],
    ['adgn/src/adgn/mcp/approval_policy/server.py'],
  ],
  rationale=|||
    Approval policy URIs use global namespace (`resource://approval-policy/policy.py`,
    `resource://approval-policy/proposals`) but should be agent-scoped like other resources
    (`resource://agents/{id}/approvals/pending`, `/history`, `/policy/proposals`, `/policy/state`, etc.).

    This creates architectural inconsistency (per-agent servers use global URIs), duplication (agents
    server exposes `resource://agents/{id}/policy/proposals` but approval policy server uses global
    namespace - which to use?), multi-agent ambiguity (global URI doesn't indicate which agent), redundant
    notifications (approvals.py:178-181 notifies both global and agent-scoped URIs), and inconsistent
    construction (manual f-strings and helpers both use global namespace).

    Replace global URIs with agent-scoped pattern `resource://agents/{agent_id}/approval-policy/...`.
    Convert constants to functions taking agent_id. Update sites: constants definition
    (mcp/_shared/constants.py:47-48), helper functions (resources.py:12, 67-69), notification calls
    (approvals.py:179 - remove), manual URI construction (agents.py:470), MCP resource registration
    (approval_policy/server.py:132, 142, 148, 161). Provides consistent namespace, clear ownership,
    no redundant notifications, matches "per-agent server" architecture.
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/_shared/constants.py': [
      [47, 48],   // Global APPROVAL_POLICY_RESOURCE_URI and PROPOSALS_INDEX_URI constants
    ],
    'adgn/src/adgn/agent/mcp_bridge/resources.py': [
      [12, 12],   // ACTIVE_POLICY global constant
      [67, 69],   // policy_proposal() helper uses global namespace
    ],
    'adgn/src/adgn/agent/approvals.py': [
      [178, 181], // Notifies both global and agent-scoped URIs
    ],
    'adgn/src/adgn/agent/mcp_bridge/servers/agents.py': [
      [470, 470], // Manual URI construction using global namespace
    ],
    'adgn/src/adgn/mcp/approval_policy/server.py': [
      [132, 132], // Resource registration using global APPROVAL_POLICY_PROPOSALS_INDEX_URI
      [142, 142], // Resource registration using global APPROVAL_POLICY_RESOURCE_URI
      [148, 148], // Resource registration using global proposals index + "/list"
      [161, 161], // Resource registration using global proposals index + "/{id}"
    ],
  },
)
