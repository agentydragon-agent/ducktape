local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    event_renderer.py lines 85-89 have an AttributeError fallback in _render_tool_result
    that can never be triggered. The try-except catches AttributeError when calling
    model_dump() on result.content blocks, falling back to raw content.

    Why unreachable: (1) CallToolResult.content (from fastmcp.client.client) contains
    MCP content types (TextContent, ImageContent, etc.), (2) all MCP content types
    are Pydantic BaseModels (from mcp.types), (3) all Pydantic models have model_dump(),
    cannot raise AttributeError, (4) FastMCP validates content via TypeAdapter before
    reaching event_renderer (calltool.py:51).

    The only way AttributeError could occur: manual construction of CallToolResult
    with non-Pydantic objects, violating type annotations. This is a programmer error
    that should fail loudly.

    Delete the try-except. Keep only: data = [block.model_dump(by_alias=True) for
    block in result.content].

    Benefits: Removes dead code, removes misleading comment, clearer code without
    defensive fallback for impossible case, violations get clear errors instead of
    silent fallback.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/event_renderer.py': [
      [85, 89],  // try/except AttributeError fallback - unreachable
    ],
  },
)
