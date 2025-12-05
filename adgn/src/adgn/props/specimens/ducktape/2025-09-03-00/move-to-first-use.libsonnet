local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    `commit_msg_path = Path(repo.git_dir) / "COMMIT_EDITMSG"` is declared many lines before its only use.
    Declare variables as close as possible to their first use to improve locality and reduce mental overhead.
    Move this assignment down to the point where it is used.
  |||,

  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[884, 884], [918, 918]],
  },
)
