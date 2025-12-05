local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    MCP abort_agent tool calls agent.abort() method that doesn't exist on MiniCodex.

    The abort_agent tool at agents.py:656 calls:
    await local_runtime.agent.abort()  # type: ignore[attr-defined]  # TODO: Implement abort() on MiniCodex

    The type ignore and TODO comment explicitly acknowledge the method is missing.

    Impact:
    - Calling abort_agent MCP tool raises AttributeError at runtime
    - Tool is unusable despite being exposed to agents/users

    The MiniCodex class only has abort_pending_tool_calls() which synthesizes
    error results for pending tool calls but doesn't provide a full abort() method.

    Fix: Implement abort() method on MiniCodex or remove the broken tool.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/servers/agents.py': [[656, 656]],
    'adgn/src/adgn/agent/agent.py': [[547, 552]],
  },
  // The issue is detectable from agents.py alone (broken call with type: ignore).
  // agent.py shows where the method should exist but absence alone isn't an issue.
  expect_caught_from=[
    ['adgn/src/adgn/agent/mcp_bridge/servers/agents.py'],
  ],
)
