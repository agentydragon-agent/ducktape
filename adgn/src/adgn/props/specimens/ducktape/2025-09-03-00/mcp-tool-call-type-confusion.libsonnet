local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    _call_mcp_tool_live uses defensive "try/except Exception: structured = None"
    guards around structuredContent access (lines 159-161) with type: ignore comments,
    suggesting the code is unsure about types. The proper MCP result type
    (mcp.types.CallToolResult) has well-defined isError, content, structuredContent,
    and meta fields. The code should use this typed model instead of defensive
    exception handling with type ignores. This type confusion appears throughout
    the function (lines 149, 152, 159, 165) where every attribute access has
    type: ignore[attr-defined].
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py': [[146, 170]],
  },
)
