local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    Two large f-strings differ only in the intro line and optional previous message. Extract a single formatter
    that builds Requirements and Context once, parameterizing the intro and optional previous-message block.

    Benefits: less duplication, easier edits to prompt policy, and consistent structure.
  |||,

  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[1110, 1120], [1121, 1128]],
  },
)
