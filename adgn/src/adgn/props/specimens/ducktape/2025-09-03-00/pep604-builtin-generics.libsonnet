local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale=|||
    Modern Python (3.11+) prefers PEP 604-style unions (e.g., `str | None`) and builtin generics (`list[int]`, `dict[str, Any]`) instead of the legacy `typing.Optional`, `typing.List`, `typing.Dict`, `typing.Tuple`, `typing.Iterator`, etc.

    Reasons to modernize:
    - Shorter, clearer, and idiomatic type hints that match current guidance and tooling.
    - Avoids indirection via typing aliases and is friendly to forward-refs / `from __future__ import annotations` usage.
    - Reduces cognitive translation for readers (they read `list[int]` directly rather than mentally mapping to `List[int]`).

  |||,
  occurrences=[
    {
      files: { 'llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/jupyter_sandbox_compose.py': [[48, 48]] },
      note: 'extra_py: Optional[str] — prefer `str | None`',
      expect_caught_from: [['llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/jupyter_sandbox_compose.py']],
    },
    {
      files: { 'llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/jupyter_mcp_launch.py': [[23, 31]] },
      note: 'log_dir: Optional[Path] — prefer `Path | None`',
      expect_caught_from: [['llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/jupyter_mcp_launch.py']],
    },
    {
      files: { 'llm/adgn_llm/src/adgn_llm/mcp/docker_exec/server.py': [[41, 41], [77, 83], [85, 100]] },
      note: 'typing imports and signatures use legacy typing names; modernize to builtin generics and PEP 604 unions',
      expect_caught_from: [['llm/adgn_llm/src/adgn_llm/mcp/docker_exec/server.py']],
    },
    {
      files: { 'llm/adgn_llm/src/adgn_llm/mini_codex/agent.py': [[7, 7], [24, 24], [76, 76], [111, 111]] },
      note: 'ToolMap and sequence/message types use typing.Dict/List — modernize',
      expect_caught_from: [['llm/adgn_llm/src/adgn_llm/mini_codex/agent.py']],
    },
    {
      files: { 'llm/adgn_llm/src/adgn_llm/mini_codex/local_server.py': [[4, 4], [19, 19]] },
      note: 'get_tools -> Dict[str, ToolDef] should use `dict[str, ToolDef]`',
      expect_caught_from: [['llm/adgn_llm/src/adgn_llm/mini_codex/local_server.py']],
    },
    {
      files: { 'llm/adgn_llm/src/adgn_llm/mini_codex/local_exec_server.py': [[3, 3], [15, 15]] },
      note: 'typing imports and return types use legacy typing names',
      expect_caught_from: [['llm/adgn_llm/src/adgn_llm/mini_codex/local_exec_server.py']],
    },
  ],
)
