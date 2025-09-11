local I = import '../../specimen_issues.libsonnet';

  I.issueOneOccurrence(
    id='iss-013b',
    rationale= |||
      Duplicate hydration/post-creation script invocation paths: a duplicate implementation exists that's
      only used by tests; production path is separate and not covered. Consolidate on the prod path.
      Suggested change: keep a single production path and make tests exercise that path.
    |||,
    properties=['no-dead-code'],
    filesToRanges={
      'wt/wt/server/worktree_service.py': [[98, 164], [299, 380]],
    },
  )
