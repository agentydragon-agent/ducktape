local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Module docstring claims tools are exposed as "mcp:{server}.{tool}" (line 12), but
    _collect_tools_live actually creates "mcp__{server}__{tool}" format (lines 121, 133).
    Docstring should match implementation.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py': [[12, 12], [121, 121], [133, 133]],
  },
)
