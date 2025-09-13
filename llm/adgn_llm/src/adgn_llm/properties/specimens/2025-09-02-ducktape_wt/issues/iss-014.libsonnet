local I = import '../../specimen_issues.libsonnet';

// iss-014: Dead code — remove unused classes and helper
I.issueOccurrencesFromLines(
  rationale='Dead code declarations; never used and should be removed.',
  properties=['no-dead-code'],
  linesByFile={
    'wt/wt/server/wt_server.py': [[413, 424, 'StatusSnapshot'], [425, 429, 'WorktreeRuntime'], [640, 1144, 'GitStatusdProcess'], [1230, 1233, '_record_github_error ']],
  },
)
