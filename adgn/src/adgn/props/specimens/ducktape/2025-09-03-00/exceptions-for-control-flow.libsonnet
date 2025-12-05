local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale=|||
    Do not use try/except to detect normal, non-error conditions. Reserve exceptions for unexpected situations.
    The current "first commit" detection relies on catching a diff failure, which can also swallow unrelated errors.
    Prefer a positive repository capability/condition check with early bailout. Example pattern:
      - If we're in the 90% normal case (without executing a failing operation), run the normal path.
      - Else, handle the 10% case explicitly.
    As a reviewer, seeing try/except signals "what's on fire" (unexpected), not a routine precondition check.
  |||,
  occurrences=[
    {
      files: { 'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [304] },
      note: 'try/except used to detect first commit instead of positive check',
      expect_caught_from: [['llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py']],
    },
  ],
)
