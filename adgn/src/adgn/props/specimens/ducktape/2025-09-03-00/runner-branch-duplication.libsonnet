local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    ParallelTaskRunner.create_and_run duplicates runner construction and update loop across branches; only output streaming differs.
    Prefer a single shared trunk: compute precommit_task (real or noop) and master_fd, construct the runner once, start the update loop once, and stream output only if master_fd is not None. This keeps the main path flat (early bailout for no-precommit).
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[590, 621]],
  },
)
