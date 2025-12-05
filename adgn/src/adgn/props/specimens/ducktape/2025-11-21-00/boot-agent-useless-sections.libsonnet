local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    The `boot_agent` docstring (lines 815-829) has Args and Returns sections that
    restate the function signature.

    Args section: "agent_id: ID of the agent to boot" restates parameter name, function
    name, and type annotation `agent_id: AgentID`.

    Returns section: "SimpleOk confirming the agent is ready" restates return type
    annotation `-> SimpleOk` and obvious success/fail pattern.

    Summary (what/why) and Raises (KeyError on missing agent) are valuable; Args/Returns
    add zero information.

    **Fix:** Delete Args/Returns sections, keep summary and Raises. Reduces docstring
    from 15 to 9 lines, no redundancy, keeps only valuable information. Args/Returns
    should only be included when they provide information beyond the type signature.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/servers/agents.py': [
      [815, 829],  // Full docstring
      [821, 825],  // Useless Args and Returns sections
    ],
  },
)
