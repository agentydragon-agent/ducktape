local I = import '../../specimen_issues.libsonnet';

// iss-008: Use walrus for include-verbose git config fallback
I.issueOneOccurrence(
  rationale= |||
    When a value is computed only to be immediately tested, prefer the walrus operator to bind-and-test in one place for clarity.
    Here, include_verbose falls back to checking git config commit.verbose via a temporary variable; use a walrus binding in the condition instead.
  |||,
  properties=['walrus'],
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[421, 429]],
  },
)
