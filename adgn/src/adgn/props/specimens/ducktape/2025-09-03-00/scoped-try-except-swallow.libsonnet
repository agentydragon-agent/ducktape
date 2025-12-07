local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale=|||
    Scoped try/except blocks swallow errors instead of failing loudly.
    Where there is no specific recovery/handling need, do not catch at all — let exceptions bubble normally.
    Where there is a specific reason to handle, catch only the narrow exception and do not swallow silently (log and/or re-raise as appropriate).
  |||,
  occurrences=[
    {
      files: { 'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [138] },
      note: 'scoped try/except swallows errors',
      expect_caught_from: [['llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py']],
    },
    {
      files: { 'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [157] },
      note: 'scoped try/except swallows errors',
      expect_caught_from: [['llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py']],
    },
    {
      files: { 'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [177] },
      note: 'scoped try/except swallows errors',
      expect_caught_from: [['llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py']],
    },
    {
      files: { 'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [196] },
      note: 'scoped try/except swallows errors',
      expect_caught_from: [['llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py']],
    },
    {
      files: { 'llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py': [[55, 59]] },
      note: 'mkdir failure silently falls back to cwd, hiding operational problems',
      expect_caught_from: [['llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py']],
    },
  ],
)
