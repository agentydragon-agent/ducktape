local I = import '../../specimen_issues.libsonnet';

// iss-064: Remove unreachable `writer is None` branch in post-creation script execution
I.issueOneOccurrence(
  id='iss-064',
  rationale='Remove unreachable `writer is None` branch in post-creation script execution; given that `_handle_worktree_create_request` is only invoked from handle_client_request with a non-None writer stream, the `writer is None` branch is dead. Remove it, unify script execution handling, and make the API contract explicit by making `writer` non-optional in the handler signature.',
  properties=['no-dead-code'],
  gap_note='GAP: Link this dead branch with the typing finding (make writer non‑optional) so the contract is explicit in the signature.',
  filesToRanges={
    'wt/wt/server/wt_server.py': [[1995,2001]],
  },
)
