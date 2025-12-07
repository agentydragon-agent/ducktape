local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    McpManager.call_tool() (lines 266-284) treats all MCP tools as if they were shell commands,
    manufacturing {"exit", "stdout", "stderr"} for everything. For local handlers that return
    dicts, it wraps them as {"exit": 0, "json": <result>} (line 281-282). This is confused
    about the abstraction: MCP tools are general-purpose operations that return CallToolResult
    (from mcp package), not necessarily shell command results. CallToolResult has proper fields
    (isError, content, structuredContent, meta) for representing tool execution results.

    The method should use CallToolResult throughout instead of manufacturing exit codes for
    non-command tools. This confusion causes issues like double-wrapping where LocalExecServer's
    {"exit": 1, "stderr": "error"} gets wrapped as {"exit": 0, "json": {"exit": 1, ...}},
    hiding failures from the agent.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py': [[266, 284]],
  },
)
