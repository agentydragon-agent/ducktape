local I = import '../../lib.libsonnet';

// Merged: walrus-assign-check-none, walrus-get-local-runtime, walrus-token-remove-comment
// All describe assign-and-check patterns that should use walrus operator

I.issueMulti(
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

  occurrences=[
    {
      files: {
        'adgn/src/adgn/agent/runtime/registry.py': [[93, 95]],
      },
      note: 'In get_agent() - assign agent row then check None',
      expect_caught_from: [['adgn/src/adgn/agent/runtime/registry.py']],
    },
    {
      files: {
        'adgn/src/adgn/agent/approvals.py': [[243, 245]],
      },
      note: 'In get_policy_proposal() - assign proposal then check None',
      expect_caught_from: [['adgn/src/adgn/agent/approvals.py']],
    },
    {
      files: {
        'adgn/src/adgn/agent/agent.py': [[335, 336]],
      },
      note: 'In agent.py - assign results.get() then check None',
      expect_caught_from: [['adgn/src/adgn/agent/agent.py']],
    },
    {
      files: {
        'adgn/src/adgn/agent/server/state.py': [[131, 133]],
      },
      note: 'In state.py - assign _find_last_tool_index then check None (occurrence 1)',
      expect_caught_from: [['adgn/src/adgn/agent/server/state.py']],
    },
    {
      files: {
        'adgn/src/adgn/agent/server/state.py': [[151, 153]],
      },
      note: 'In state.py - assign _find_last_tool_index then check None (occurrence 2)',
      expect_caught_from: [['adgn/src/adgn/agent/server/state.py']],
    },
    {
      files: {
        'adgn/src/adgn/agent/server/state.py': [[176, 178]],
      },
      note: 'In state.py - assign _find_last_tool_index then check None (occurrence 3)',
      expect_caught_from: [['adgn/src/adgn/agent/server/state.py']],
    },
    {
      files: {
        'adgn/src/adgn/agent/mcp_bridge/auth.py': [[93, 95]],
      },
      note: 'In get_agent_id() - assign token lookup then check None',
      expect_caught_from: [['adgn/src/adgn/agent/mcp_bridge/auth.py']],
    },
    {
      files: {
        'adgn/src/adgn/agent/mcp_bridge/servers/agents.py': [[327, 329]],
      },
      note: 'In servers/agents.py - assign get_local_runtime then check None (occurrence 1)',
      expect_caught_from: [['adgn/src/adgn/agent/mcp_bridge/servers/agents.py']],
    },
    {
      files: {
        'adgn/src/adgn/agent/mcp_bridge/servers/agents.py': [[351, 353]],
      },
      note: 'In servers/agents.py - assign get_local_runtime then check None (occurrence 2)',
      expect_caught_from: [['adgn/src/adgn/agent/mcp_bridge/servers/agents.py']],
    },
    {
      files: {
        'adgn/src/adgn/agent/mcp_bridge/servers/agents.py': [[374, 376]],
      },
      note: 'In servers/agents.py - assign get_local_runtime then check None (occurrence 3)',
      expect_caught_from: [['adgn/src/adgn/agent/mcp_bridge/servers/agents.py']],
    },
    {
      files: {
        'adgn/src/adgn/agent/mcp_bridge/server.py': [[162, 163]],
      },
      note: 'In server.py - assign for ternary expression',
      expect_caught_from: [['adgn/src/adgn/agent/mcp_bridge/server.py']],
    },
    {
      files: {
        'adgn/src/adgn/agent/server/mcp_routing.py': [[107, 111]],
      },
      note: 'In mcp_routing.py - dict.get with useless "Look up token" comment',
      expect_caught_from: [['adgn/src/adgn/agent/server/mcp_routing.py']],
    },
  ],
)
