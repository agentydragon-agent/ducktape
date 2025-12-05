local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Function extract_structured_content accepts both FMCallToolResult and mcp_types.CallToolResult, making type reasoning harder.
    This loose typing forces runtime normalization and isinstance checks throughout the function.
    The function should accept only mcp_types.CallToolResult, and callers should explicitly convert using fastmcp_to_mcp_result if needed.
    This pushes the conversion to the boundary, making the core logic simpler and type-safe.
  |||,
  filesToRanges={'adgn/src/adgn/mcp/_shared/calltool.py': [56]},
)
