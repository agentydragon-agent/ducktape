local I = import '../../specimens/lib.libsonnet';

// iss-061: Replace quoted return annotations with real type (annotations future enabled)
I.issueOneOccurrence(
  rationale=|||
    The module already enables postponed evaluation of annotations via `from __future__ import annotations`,
    but still uses quoted return annotations:

      @classmethod
      async def from_config(...) -> "McpManager":
      ...
      @classmethod
      async def from_servers(...) -> "McpManager":

    Prefer non-quoted annotations (`-> McpManager`) for clarity and consistency.
  |||,
  // properties=['type-hints'],
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py': [[191, 191], [226, 226]],
  },
)
