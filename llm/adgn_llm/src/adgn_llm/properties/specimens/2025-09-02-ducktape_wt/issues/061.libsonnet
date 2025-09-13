local I = import '../../specimens/lib.libsonnet';

// iss-061: Inline one-off temp for is_git_repository
I.issueOneOccurrence(
  rationale='Avoid single-use temporary variables; prefer direct expressions at the call site to reduce noise and improve clarity. Suggested change for lines 204-205: replace the two-step flag/compare with `is_git_repository = int(fields[1]) == 1`.',
  // properties=['no-oneoff-vars-and-trivial-wrappers'],
  filesToRanges={
    'wt/wt/server/gitstatusd_client.py': [[204, 205]],
  },
)
