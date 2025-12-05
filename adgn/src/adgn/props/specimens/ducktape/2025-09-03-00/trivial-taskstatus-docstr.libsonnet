local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    The docstring "Status of a task." adds no information beyond the class name `TaskStatus` and repeats
    the obvious. Trivial docstrings like this create noise without signal; remove them.
  |||,

  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[468, 470]],
  },
)
