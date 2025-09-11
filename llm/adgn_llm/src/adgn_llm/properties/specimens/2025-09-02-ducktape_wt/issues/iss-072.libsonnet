local I = import '../../specimen_issues.libsonnet';

// iss-072: Remove dead `branch_status` in gitstatusd_client
I.issueOneOccurrence(
  id='iss-072',
  rationale='`branch_status` is dead code in gitstatusd_client and should be removed; presentation/view concerns (branch display state) belong in the client/view layer rather than the core client.',
  properties=['no-dead-code'],
  gap_note='GAP: Presentation/view concerns (branch display state) should not live in the core client.',
  filesToRanges={
    'wt/wt/server/gitstatusd_client.py': [[143,163]],
  },
)
