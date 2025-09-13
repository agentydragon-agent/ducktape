local I = import '../../specimen_issues.libsonnet';

// iss-056: Remove trivial docstring that repeats the class name
I.issueOneOccurrence(
  rationale= |||
    The docstring "Status of a task." adds no information beyond the class name `TaskStatus` and repeats
    the obvious. Trivial docstrings like this create noise without signal; remove them.
  |||,
  properties=['no-useless-docs'],
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[468,470]],
  },
)
