local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    Avoid quoted return annotations (e.g. `-> "McpManager"`). Enable `from __future__ import annotations` at module top and use real types (e.g., `-> McpManager`) or PEP 604 unions where appropriate.

    Why this matters:
    - Quoted annotations are a historical workaround; modern code should use postponed evaluation (`from __future__ import annotations`) so annotations are real types for static tools while avoiding runtime evaluation costs and string fragility.
    - Removing quotes improves clarity, IDE/type-checker support, and reduces bugs where strings are misspelled or not updated during refactors.

    Suggested fix: add `from __future__ import annotations` at the module top and replace quoted return/type annotations with the direct types (optionally keep `typing` imports minimal when needed).
  |||,
  occurrences=[
    {
      files: {'llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py': [[184, 192]]},
      note: 'Multiple quoted return annotations in methods',
      expect_caught_from: [['llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py']],
    },
    {
      files: {'llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py': [[191, 191], [226, 226]]},
      note: 'from_config and from_servers classmethods use -> "McpManager" despite __future__ annotations enabled',
      expect_caught_from: [['llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py']],
    },
  ],
)
