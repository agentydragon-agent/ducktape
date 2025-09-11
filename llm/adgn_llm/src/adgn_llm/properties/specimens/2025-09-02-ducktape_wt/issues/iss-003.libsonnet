local I = import '../../specimen_issues.libsonnet';

  // iss-003: Markdown inline formatting for identifiers/flags/paths/URIs
  I.issueOccurrencesFromLines(
    id='iss-003',
    rationale='Use Markdown inline code for environment variable names (e.g., WT_DIR).',
    properties=['inline-formatting'],
    linesByFile={
      'wt/ARCHITECTURE.md': [256, 259],
      'wt/WORKTREE_IDEAS.md': [7, 16],
      'wt/tests/README.md': [68, 71],
    },
  )
