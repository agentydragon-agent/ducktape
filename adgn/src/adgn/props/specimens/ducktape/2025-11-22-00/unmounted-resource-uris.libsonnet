local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    The `resources.py` module defines ten parameterized resource URI helper functions
    (agent_state, agent_snapshot, agent_mcp_state, agent_approvals_pending, agent_approvals_history,
    agent_approval, agent_policy_proposals, agent_policy_state, agent_session_state, agent_ui_state)
    that construct URIs like `resource://agents/{agent_id}/state`, but only two URIs are actually
    mounted as resources in the MCP server: `resource://agents/list` and `resource://agents/{agent_id}/info`
    (server.py, lines 251-284).

    **Problems:**
    1. Dead code: 10 URI helpers defined but never used
    2. Confusing API: functions suggest resources exist when they don't
    3. Maintenance burden: unused code + misleading docstrings
    4. No clear plan: unclear if future features or abandoned work
    5. Constants duplication: same URIs also in `_shared/constants.py`

    **The correct approach:**
    Either implement the missing resources or delete the unused helpers. Recommended: delete helpers
    for unmounted resources, keeping only what's actually implemented. Search for usages first; if used
    only in tests expecting future work, move to test fixtures.

    **Benefits of cleanup:**
    1. No dead code, clear API surface
    2. Less confusion for new developers
    3. Honest documentation reflecting actual capabilities
    4. Smaller maintenance burden
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/resources.py': [
      [16, 67],  // All unmounted URI helper functions (agent_state through agent_ui_state)
    ],
  },
)
