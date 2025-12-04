local I = import '../../lib.libsonnet';

// iss-018: Prefer postponed/evaluated type annotations over quoted return annotations
I.issue(
  rationale=|||
    Avoid quoted return annotations (e.g. `-> "McpManager"`). Enable `from __future__ import annotations` at module top and use real types (e.g., `-> McpManager`) or PEP 604 unions where appropriate.

    Why this matters:
    - Quoted annotations are a historical workaround; modern code should use postponed evaluation (`from __future__ import annotations`) so annotations are real types for static tools while avoiding runtime evaluation costs and string fragility.
    - Removing quotes improves clarity, IDE/type-checker support, and reduces bugs where strings are misspelled or not updated during refactors.

    Suggested fix: add `from __future__ import annotations` at the module top and replace quoted return/type annotations with the direct types (optionally keep `typing` imports minimal when needed).
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py': [[184, 192]],
  },
)
