local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale=|||
    Function-local imports hide dependencies and impede static analysis and import-time reasoning. Move imports to module level unless there's a compelling runtime justification (e.g., optional heavy dependency, import-time side effects to avoid, or to break import cycles).

    Prefer module-level imports to keep dependency graphs visible and simplify testing and bundling.
  |||,
  occurrences=[
    {
      files: { 'llm/adgn_llm/src/adgn_llm/mini_codex/agent.py': [[29, 29], [46, 46], [85, 85]] },
      note: 'function-local imports: _is_retryable, _openai_client, load_mcp_file',
      expect_caught_from: [['llm/adgn_llm/src/adgn_llm/mini_codex/agent.py']],
    },
    {
      files: { 'llm/adgn_llm/src/adgn_llm/mini_codex/cli.py': [[87, 87]] },
      note: 'function-local import in _run_proc',
      expect_caught_from: [['llm/adgn_llm/src/adgn_llm/mini_codex/cli.py']],
    },
    {
      files: { 'llm/adgn_llm/src/adgn_llm/mini_codex/local_tools.py': [[26, 26]] },
      note: 'function-local import in _run_proc',
      expect_caught_from: [['llm/adgn_llm/src/adgn_llm/mini_codex/local_tools.py']],
    },
    {
      files: { 'llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py': [[101, 101]] },
      note: 'function-local import in _sanitize_name',
      expect_caught_from: [['llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py']],
    },
  ],
)
