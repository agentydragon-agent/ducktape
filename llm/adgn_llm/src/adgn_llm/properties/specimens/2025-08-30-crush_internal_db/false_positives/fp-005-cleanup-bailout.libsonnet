local I = import '../../specimen_issues.libsonnet';

// fp-005-cleanup-bailout
// False positive: cleanup loop early-bailout rewrite not necessary

I.issueOneOccurrence(
  should_flag=false,
  rationale=|||
    A reviewer suggested refactoring the cleanup loop in internal/app/app.go from:

      for _, cleanup := range app.cleanupFuncs {
          if cleanup != nil {
              cleanup()
          }
      }

    to an early-bailout style using `continue` when cleanup == nil. This is a false positive. The
    existing form is brief and clear; rewriting to use `continue` yields no measurable improvement and
    is not necessary. Keep as-is.
  |||,
  properties=[],
  filesToRanges={
    'internal/app/app.go': [[200, 206]],
  },
)
