local I = import '../../lib.libsonnet';

// Merged: create-agent-useless-comments, misleading-required-comments
// Both describe comments that add no value (obvious or misleading)

I.issue(
  expect_caught_from=[
    ['adgn/src/adgn/agent/mcp_bridge/servers/agents.py'],
    ['adgn/src/adgn/agent/persist/__init__.py'],
  ],
  rationale= |||
    Comments that add no value: either restating obvious code or providing
    incorrect information about field requirements.

    **Pattern 1: Obvious operation comments** (agents.py:785-792)
    Lines 785-792 have three comments that merely restate simple operations:
    generating an agent ID, calling create_agent, and returning a brief.
    Function already has a docstring; these add noise without information.

    **Pattern 2: Incorrect "REQUIRED" comments** (persist/__init__.py)
    Three Pydantic models claim "All fields are REQUIRED" but have optional
    fields with defaults (e.g., Decision.reason has default None). Pydantic
    type annotations already define requirements; comments contradict the code.

    **Problems:**
    - Noise obscures actual code
    - Comments become stale/incorrect as code evolves
    - Redundant: code and type annotations already show what's required
    - Maintenance burden keeping comments synchronized

    **Fix:** Delete these comments. Code operations and Pydantic annotations
    are self-documenting. Comments should explain WHY, not restate WHAT.
  |||,

  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/servers/agents.py': [
      [785, 792],  // Function body with useless comments and empty lines
      [785, 785],  // Comment: "Generate unique agent ID"
      [787, 787],  // Empty line
      [788, 788],  // Comment: "Create infrastructure for the agent"
      [790, 790],  // Empty line
      [791, 791],  // Comment: "Return agent brief with the created agent's ID"
    ],
    'adgn/src/adgn/agent/persist/__init__.py': [
      [90, 98],    // Decision class with misleading "All fields are REQUIRED" comment
      [93, 93],    // Line with incorrect comment
      [101, 109],  // ToolCallExecution class with misleading "All fields are REQUIRED" comment
      [104, 104],  // Line with redundant comment
      [123, 123],  // agent_id with redundant "# REQUIRED" inline comment
    ],
  },
)
