local I = import '../../specimens/lib.libsonnet';

// iss-015: No dead code — DisabledGitHubInterface is unused
I.issueOccurrencesFromLines(
  rationale='DisabledGitHubInterface is not referenced; remove the dead class.',
  // properties=['no-dead-code'],
  linesByFile={
    'wt/wt/server/github_client.py': [[18, 36, 'DisabledGitHubInterface']],
  },
)
