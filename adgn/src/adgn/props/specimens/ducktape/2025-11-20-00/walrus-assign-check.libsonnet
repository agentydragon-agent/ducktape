local I = import '../../lib.libsonnet';

// Merged: walrus-assign-check-none, walrus-get-local-runtime, walrus-token-remove-comment
// All describe assign-and-check patterns that should use walrus operator

I.issueMulti(
  rationale= |||
    Twelve locations use assign-then-check patterns instead of walrus operator (:=). Common patterns:
    assign value then check if None (registry.py:93-95, approvals.py:243-245, agent.py:335-336),
    assign for ternary/conditional (server.py:162-163), dict.get with None check (mcp_routing.py:107-111
    with useless "Look up token" comment), and multiple occurrences of assign-then-None-check in
    state.py (lines 131-133, 151-153, 176-178) and servers/agents.py (lines 327-329, 351-353, 374-376).

    Use walrus operator to combine assignment and condition: `if (row := await get_agent(...)) is None`,
    `return x.y if (x := expr) else None`, `if not (info := dict.get(...)): ...`. This is more concise
    (combines two lines into one), clearer scope (variable exists only where needed), and standard Python
    idiom (PEP 572). Not applicable when variable is reassigned inside conditional block.
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
