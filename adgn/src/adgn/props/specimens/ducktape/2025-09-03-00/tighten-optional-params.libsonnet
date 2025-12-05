local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale=|||
    Optional parameters should only be typed optional when None is a real, exercised state.
    When callers always pass a value (or a default is always resolved), drop `| None = None` to tighten contracts and avoid ambiguous call sites.
  |||,
  occurrences=[
    {
      files: { 'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[280, 281]] },
      note: '`previous_message` default — confirm if None is truly exercised; otherwise make it required or resolve before call',
      expect_caught_from: [['llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py']],
    },
    {
      files: { 'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[1013, 1013]] },
      note: 'generate(..., model: str | None = None) — prefer required or resolve default at call site',
      expect_caught_from: [['llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py']],
    },
    {
      files: { 'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[1103, 1103]] },
      note: 'generate(..., model: str | None = None) — prefer required or resolve default at call site',
      expect_caught_from: [['llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py']],
    },
  ],
)
