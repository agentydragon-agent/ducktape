local I = import '../../specimens/lib.libsonnet';

// iss-027: Should use walrus operator for assign-and-check-None pattern

I.issueOneOccurrence(
  rationale=|||
    Code assigns value then immediately checks if None, where walrus operator
    would be clearer and more concise.

    Current pattern (registry.py:93-95):
    row = await self.persistence.get_agent(agent_id)
    if row is None:
        raise KeyError(f"agent not found: {agent_id}")

    Should use walrus:
    if (row := await self.persistence.get_agent(agent_id)) is None:
        raise KeyError(f"agent not found: {agent_id}")

    Other occurrences:
    - approvals.py:243-245: get_policy_proposal then check
    - agent.py:335-336: results.get then check
    - state.py:131-133, 151-153, 176-178: _find_last_tool_index then check
    - auth.py:93-95: get_agent_id then check
    - servers/agents.py:327-329, 351-353, 374-376: get_local_runtime then check

    Benefits of walrus operator:
    - More concise: combines assignment and condition
    - Clearer scope: variable only exists where needed
    - Standard Python idiom (PEP 572)
    - Reduces line count

    Note: Not applicable when variable is reassigned inside if block.
  |||,
  properties=['python/walrus-operator'],
  filesToRanges={
    'adgn/src/adgn/agent/runtime/registry.py': [
      [93, 95],     // get_agent then check
    ],
    'adgn/src/adgn/agent/approvals.py': [
      [243, 245],   // get_policy_proposal then check
    ],
    'adgn/src/adgn/agent/agent.py': [
      [335, 336],   // results.get then check
    ],
    'adgn/src/adgn/agent/server/state.py': [
      [131, 133],   // _find_last_tool_index then check (3 occurrences)
      [151, 153],
      [176, 178],
    ],
    'adgn/src/adgn/agent/mcp_bridge/auth.py': [
      [93, 95],     // get_agent_id then check
    ],
    'adgn/src/adgn/agent/mcp_bridge/servers/agents.py': [
      [327, 329],   // get_local_runtime then check (3 occurrences)
      [351, 353],
      [374, 376],
    ],
  },
)
