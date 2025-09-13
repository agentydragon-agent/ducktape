local I = import '../../specimen_issues.libsonnet';

// iss-063: Remove archaeology-style comment that restates current code
I.issueOneOccurrence(
  rationale= |||
    The comment "Factor out task creation to a single place" restates the next line and carries historical intent
    rather than present-tense signal. Remove such archaeology comments to keep code concise and current.
  |||,
  properties=['no-useless-docs'],
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[873,873]],
  },
)
