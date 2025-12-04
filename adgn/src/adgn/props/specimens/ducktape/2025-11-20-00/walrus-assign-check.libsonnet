local I = import '../../lib.libsonnet';

// Merged: walrus-assign-check-none, walrus-get-local-runtime, walrus-token-remove-comment
// All describe assign-and-check patterns that should use walrus operator

I.issue(
  rationale= |||
    Code uses assign-then-check patterns where walrus operator (:=) would be
    clearer and more concise. Common patterns include:

    1. Assign value, then check if None:
       row = await self.persistence.get_agent(agent_id)
       if row is None:
           raise KeyError(...)

    2. Assign for ternary/conditional:
       agent = self._agents[agent_id].agent
       return agent.local_runtime if agent else None

    3. Dict.get with None check (often with useless comment):
       # Look up token
       token_info = self.token_table.get(token)
       if not token_info:
           return Response(...)

    All should use walrus operator (PEP 572):
    - More concise: combines assignment and condition
    - Clearer scope: variable exists only where needed
    - Standard Python idiom for assign-and-check
    - Reduces line count without hurting readability

    Examples of conversion:

    Pattern 1 (assign + None check):
    if (row := await self.persistence.get_agent(agent_id)) is None:
        raise KeyError(...)

    Pattern 2 (assign + ternary):
    return agent.local_runtime if (agent := self._agents[agent_id].agent) else None

    Pattern 3 (dict.get + None check):
    if not (token_info := self.token_table.get(token)):
        return Response(...)

    Note: Not applicable when variable is reassigned inside conditional block.
  |||,

  filesToRanges={
    'adgn/src/adgn/agent/runtime/registry.py': [
      [93, 95],     // get_agent then check None
    ],
    'adgn/src/adgn/agent/approvals.py': [
      [243, 245],   // get_policy_proposal then check None
    ],
    'adgn/src/adgn/agent/agent.py': [
      [335, 336],   // results.get then check None
    ],
    'adgn/src/adgn/agent/server/state.py': [
      [131, 133],   // _find_last_tool_index then check None
      [151, 153],
      [176, 178],
    ],
    'adgn/src/adgn/agent/mcp_bridge/auth.py': [
      [93, 95],     // get_agent_id then check None
    ],
    'adgn/src/adgn/agent/mcp_bridge/servers/agents.py': [
      [327, 329],   // get_local_runtime then check None
      [351, 353],
      [374, 376],
    ],
    'adgn/src/adgn/agent/mcp_bridge/server.py': [
      [162, 163],   // Assign for ternary expression
    ],
    'adgn/src/adgn/agent/server/mcp_routing.py': [
      [107, 111],   // Dict.get with useless "Look up token" comment
    ],
  },
  expect_caught_from=[
    ['adgn/src/adgn/agent/runtime/registry.py'],
    ['adgn/src/adgn/agent/approvals.py'],
    ['adgn/src/adgn/agent/agent.py'],
    ['adgn/src/adgn/agent/server/state.py'],
    ['adgn/src/adgn/agent/mcp_bridge/auth.py'],
    ['adgn/src/adgn/agent/mcp_bridge/servers/agents.py'],
    ['adgn/src/adgn/agent/mcp_bridge/server.py'],
    ['adgn/src/adgn/agent/server/mcp_routing.py'],
  ],
)
