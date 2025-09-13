local I = import '../../specimens/lib.libsonnet';

// iss-046: parse_gitstatusd_response thin wrapper (dead)
I.issueOneOccurrence(
  rationale='`parse_gitstatusd_response` is a thin wrapper around GitStatusdProtocol; migrate callers to Protocol methods and delete.',
  // properties=['no-dead-code'],
  filesToRanges={
    'wt/wt/server/gitstatusd_client.py': [[358, 358]],
  },
)
