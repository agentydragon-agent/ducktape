local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    The `try/except` around `mcp_manager.instruction_block()` appears twice with identical logic
    (once in the plain-turn path and once in the tool-call path). Extract a small helper (e.g.,
    `_append_mcp_instructions(base: str, m: McpManager|None) -> str`) and reuse it in both places.

    This reduces duplication, centralizes the narrow exception handling decision, and keeps
    the instruction composition logic consistent across call sites.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mini_codex/cli.py': [[199, 204], [285, 290]],
  },
)
