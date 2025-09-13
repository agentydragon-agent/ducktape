local I = import '../../specimen_issues.libsonnet';

// iss-043: gitstatusd_client convenience wrappers are dead
I.issueWithOccurrences(
  rationale='dead code: `parse_gitstatusd_response` (L358), `create_gitstatusd_request` (L363) — thin wrappers around GitStatusdProtocol; migrate callers to Protocol methods and delete.',
  properties=['no-dead-code'],
  occurrences=[
    { files: { 'wt/wt/server/gitstatusd_client.py': [358] } },
    { files: { 'wt/wt/server/gitstatusd_client.py': [363] } },
  ],
)
