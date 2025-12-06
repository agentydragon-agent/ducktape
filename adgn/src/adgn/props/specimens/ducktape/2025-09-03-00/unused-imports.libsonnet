local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Unused imports.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/jupyter_sandbox_compose.py': [[5, 6]],
  },
)
