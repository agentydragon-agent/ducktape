local I = import '../../specimen_issues.libsonnet';

// iss-047: create_gitstatusd_request thin wrapper (dead)
I.issueOneOccurrence(
  rationale='`create_gitstatusd_request` is a thin wrapper around GitStatusdProtocol; migrate callers to Protocol methods and delete.',
  properties=['no-dead-code'],
  filesToRanges={
    'wt/wt/server/gitstatusd_client.py': [[363, 363]],
  },
)
