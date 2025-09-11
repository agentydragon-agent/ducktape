local I = import '../../specimen_issues.libsonnet';

  // iss-030: No dead code — GitHub models unused types
  I.issueOccurrencesFromLines(
    id='iss-030',
    rationale='Dead/unused GitHub types: PullRequest (L65), PullRequestView (L92), PullRequestCache; remove or consolidate.',
    properties=['no-dead-code'],
    linesByFile={
      'wt/wt/shared/github_models.py': [[65, 75, 'PullRequest'], [92, 104, 'PullRequestView'], [105, 136, 'PullRequestCache']],
    },
  )
