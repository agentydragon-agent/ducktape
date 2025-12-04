local I = import '../../lib.libsonnet';


I.issue(
  expect_caught_from=[['adgn/src/adgn/agent/mcp_bridge/servers/registry_bridge.py'], ['adgn/src/adgn/agent/mcp_bridge/servers/approvals_bridge.py']],
  rationale=|||
    Multiple functions have Args sections in docstrings that simply restate information
    already obvious from type annotations and parameter names.

    Examples: `create_agent(agent_id: AgentID)` documents "Unique identifier for the new
    agent" (obvious from type and name), `approve(call_id: str, reasoning: str | None)`
    documents "ID of the tool call" and "Optional reasoning" (obvious from types).

    Args sections should explain WHY or HOW, not WHAT (already clear from signature).
    Remove Args that restate type info. Keep only Args that add non-obvious semantic
    information (e.g., retry behavior, validation rules, side effects).

    Affected: registry_bridge.py lines 142-143, 170-171; approvals_bridge.py lines 125-127,
    141-143.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/servers/registry_bridge.py': [
      [142, 143], // create_agent Args
      [170, 171], // delete_agent Args
    ],
    'adgn/src/adgn/agent/mcp_bridge/servers/approvals_bridge.py': [
      [125, 127], // approve Args
      [141, 143], // reject Args
    ],
  },
)
