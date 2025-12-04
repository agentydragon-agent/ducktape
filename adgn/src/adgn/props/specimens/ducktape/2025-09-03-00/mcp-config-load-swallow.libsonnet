local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    The code currently conditionally reads an MCP config only if the file exists. That’s fine. The problem is the broad except that silently ignores *errors parsing or using the file*. If the .mcp.json exists but is malformed or otherwise unusable, the program must crash loudly so operator/CI notices and fixes the problem; do NOT silently ignore a present-but-broken config file.

    Swallowing initialization-time parsing/shape errors leads to silently degraded runtime behavior and hard-to-diagnose failures later. If the file exists, treat errors parsing/using it as fatal.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mini_codex/cli.py': [[336, 346]],
  },
)
