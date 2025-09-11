local I = import '../../specimen_issues.libsonnet';

  // iss-016: No dead code — remove unused guard helpers and parser finalize
  I.issueOccurrencesFromLines(
    id='iss-016',
    rationale='Dead code: remove unused guard helpers and parser finalize method.',
    properties=['no-dead-code'],
    linesByFile={
      'wt/wt/shared/models.py': [[40, 42, 'Worktree.require_exists'], [44, 46, 'Worktree.require_not_exists'], [145, 151, 'WorktreeParseState.finalize']],
    },
  )
