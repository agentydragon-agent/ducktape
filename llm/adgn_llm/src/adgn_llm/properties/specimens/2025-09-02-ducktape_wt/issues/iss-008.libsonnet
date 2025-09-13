local I = import '../../specimen_issues.libsonnet';

// iss-008: Narrow try scope in _refresh_github_cache
I.issueOneOccurrence(
  rationale=|||
    `_refresh_github_cache` swallows exceptions and returns silently in non-boundary code.
    Narrow the try to the minimal risky repo access.
    Catch specific exceptions or let them propagate, and log appropriately.
  |||,
  properties=['scoped-try-except'],
  filesToRanges={
    'wt/wt/server/wt_server.py': [[586, 593]],
  },
)
