local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    InfrastructureRegistry.get() method is called but does not exist in the class definition.

    The calls should likely use get_running_infrastructure() instead,
    based on the usage pattern where the result is checked for None.
  |||,
  occurrences=[
    {
      files: {
        'adgn/src/adgn/agent/server/status_shared.py': [[114, 114]],
      },
      note: 'Called in build_agent_status_core: c = registry.get(agent_id)',
      expect_caught_from: [['adgn/src/adgn/agent/server/status_shared.py']],
    },
    {
      files: {
        'adgn/src/adgn/agent/mcp_bridge/servers/agents.py': [[516, 516]],
      },
      note: 'Called in agent_ui_state_resource: runtime = registry.get(agent_id)',
      expect_caught_from: [['adgn/src/adgn/agent/mcp_bridge/servers/agents.py']],
    },
  ],
)
