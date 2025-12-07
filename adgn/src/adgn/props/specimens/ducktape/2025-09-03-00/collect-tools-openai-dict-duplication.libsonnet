local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    _collect_tools_live has duplicated logic for building openai_tools dict entries.
    The stdio branch (lines 121-128) and local branch (lines 133-140) create identical
    dict structures with "type", "name", "description", "parameters" keys. Should extract
    a helper function that takes (server, tool_name, description, params_schema) and
    returns the tool dict, then call it from both branches. This would eliminate 8 lines
    of duplication and make the tool dict structure easier to maintain.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py': [[121, 128], [133, 140]],
  },
)
