local I = import '../../specimen_issues.libsonnet';

// iss-029-argumentsblocker-labeled-continue
// ArgumentsBlocker: use labeled continue instead of sentinel flag in inner loop to reduce nesting/noise

I.issueOneOccurrence(
  id='iss-029-argumentsblocker-labeled-continue',
  rationale='ArgumentsBlocker in internal/shell/shell.go uses a sentinel flag inside an inner loop to decide post-loop behavior. Prefer a labeled continue to skip to the next outer iteration and keep the happy-path less indented.',
  properties=['minimize-nesting'],
  filesToRanges={
    'internal/shell/shell.go': [[183,201]],
  },
)
