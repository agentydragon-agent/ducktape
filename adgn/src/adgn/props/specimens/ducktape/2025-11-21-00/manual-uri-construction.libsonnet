local I = import '../../lib.libsonnet';


I.issue(
  expect_caught_from=[
    ['adgn/src/adgn/agent/mcp_bridge/servers/agents.py'],
    ['adgn/src/adgn/mcp/_shared/constants.py'],
  ],
  rationale=|||
    Line 407 in agents.py manually constructs a resource URI using an f-string
    instead of using a centralized constant from _shared/constants.py. The codebase
    has URI format constants (e.g., AGENTS_APPROVALS_PENDING_URI_FMT) but individual
    approval URIs are constructed inline.

    **Problems:**
    - Violates centralization principle (constants.py exists for this)
    - Inconsistent with rest of codebase which imports URI constants
    - Hard to change URI patterns globally
    - Risk of typos in manual construction
    - No single source of truth for URI patterns

    **Fix:** Add AGENTS_APPROVAL_URI_FMT constant to constants.py, then import and
    use it: `AGENTS_APPROVAL_URI_FMT.format(agent_id=..., call_id=...)`. This pattern
    should apply to all manual URI constructions in the codebase.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/servers/agents.py': [
      [407, 407],  // Manual URI construction
    ],
    'adgn/src/adgn/mcp/_shared/constants.py': [
      [57, 60],  // Existing agent URI constants (for context)
    ],
  },
)
