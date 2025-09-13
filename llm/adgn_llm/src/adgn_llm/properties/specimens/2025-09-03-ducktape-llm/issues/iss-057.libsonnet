local I = import '../../specimen_issues.libsonnet';

// iss-057: Remove trivial comment that restates the code
I.issueOneOccurrence(
  rationale= |||
    The comment `# Print the status` restates the very next line and adds no signal. Remove trivial
    comments that merely narrate the code without adding context or rationale.
  |||,
  properties=['no-useless-docs'],
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[694,695]],
  },
)
