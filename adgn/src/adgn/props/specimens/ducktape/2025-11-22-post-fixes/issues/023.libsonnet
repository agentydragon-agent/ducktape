local I = import '../../specimens/lib.libsonnet';

// iss-023: Unmounted resource URIs in resources.py

I.issueOneOccurrence(
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
  properties=['remove-dead-code', 'avoid-speculative-code'],
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/resources.py': [
      [16, 67],  // All unmounted URI helper functions (agent_state through agent_ui_state)
    ],
  },
  gap_note= |||
    This finding illustrates **"avoid-speculative-code"**: don't write infrastructure
    for features that aren't implemented yet. Either implement the feature completely or
    don't add the infrastructure.

    Speculative code causes:
    - Dead code that never gets used (increases maintenance burden)
    - Misleading APIs (functions suggest capabilities that don't exist)
    - Confusion (is this a bug, or intentionally unimplemented?)
    - Broken windows (more speculative code gets added because it exists)

    The principle: write code when you need it, not when you might need it.

    Exceptions (when speculative code is acceptable):
    - Explicit feature flags or capability detection (so code knows what's available)
    - Well-documented TODOs or NotImplementedError stubs (make intent clear)
    - Interface definitions in a stable API contract (but mark unimplemented methods)

    Related to **"remove-dead-code"**: once you identify that code is unused, delete it.
    Don't keep it around "just in case" - version control preserves history if needed later.

    When you find helper functions that construct identifiers/URIs for things that
    don't exist:
    1. Check if they're used anywhere (search imports)
    2. If used only in tests expecting future work: move to test fixtures
    3. If unused: delete immediately
    4. If implementing: add the actual functionality at the same time
  |||,
)
