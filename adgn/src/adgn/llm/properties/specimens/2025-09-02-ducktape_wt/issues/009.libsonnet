local I = import '../../specimens/lib.libsonnet';

// iss-009: PRService.get_pr_info overbroad exception handling
I.issueOneOccurrence(
  rationale=|||
    In `PRService.get_pr_info`, a blanket `except Exception` in non-boundary code silently swallows
    errors and the try wraps a long block. Scope the try to just the GitHub call and catch specific
    expected exceptions (or let them propagate) with proper logging.
  |||,
  // properties=['scoped-try-except'],
  filesToRanges={
    'wt/wt/server/wt_server.py': [[613, 635]],
  },
)
