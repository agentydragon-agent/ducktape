local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    `mtime_s = path.stat().st_mtime` is used once immediately in the condition; inline the expression to
    reduce one-off locals and keep the check compact.
  |||,

  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[463, 465]],
  },
)
