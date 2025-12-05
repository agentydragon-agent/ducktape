local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    The from_server classmethod spans 69 lines (109-178), with a single for-loop body
    consuming 49 lines (128-177). This makes the method difficult to understand and maintain.

    Problems: single method doing too many things (registry access, tool introspection,
    type resolution, model extraction), 49-line loop body extremely hard to read, multiple
    nested try/except blocks and conditionals within loop, mixing different concerns,
    hard to test individual introspection logic pieces.

    Extract loop body into a static helper method _extract_tool_models(tool) that returns
    tuple[str, ToolModels] | None. Simplify main loop to call helper, check result, and
    store. Benefits: single responsibility per method, easier to understand flow, helper
    testable independently, reduced cognitive load.
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/stubs/typed_stubs.py': [
      [109, 178],  // Entire from_server method
      [128, 177],  // Giant for-loop body that should be extracted
    ],
  },
)
