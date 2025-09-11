local I = import '../../specimen_issues.libsonnet';

  I.issueOccurrencesFromLines(
    id='iss-013c',
    rationale='Dead code; should be deleted.',
    properties=['no-dead-code'],
    linesByFile={
      'wt/wt/server/git_manager.py': [[40, 41, 'get_status_porcelain'], [200, 224, 'status_porcelain',], [310, 312, 'rev_count()'], [313, 315, 'CannotDeleteWorktree']],
    },
  )
