local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The create_agent tool accepts preset and system_message parameters and documents them in its
    docstring, but the implementation generates an ID and calls registry.create_agent(agent_id)
    without using either parameter. The tool does not fulfill its documented contract.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/servers/agents.py': [[777, 798]],
  },
)
