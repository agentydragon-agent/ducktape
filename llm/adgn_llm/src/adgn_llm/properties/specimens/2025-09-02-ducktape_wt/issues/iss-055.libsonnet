local I = import '../../specimen_issues.libsonnet';

// iss-055: Early bailout and guard clauses in worktree_list and identify
I.issueWithOccurrences(
  id='iss-055',
  rationale='Use early bailout/guard clauses to reduce nesting and make the happy path obvious in list and identify handlers.',
  properties=['early-bailout'],
  occurrences=[
    { files: { 'wt/wt/server/wt_server.py': [[2149,2156]] }, note: 'In worktree_list: replace nested block with guard `continue` to keep loop body flat.' },
    { files: { 'wt/wt/server/wt_server.py': [[2175,2185]] }, note: 'In _handle_worktree_identify_request: invert `if worktree_name and absolute_path.exists()` to early return (negative guard).' },
  ],
)
