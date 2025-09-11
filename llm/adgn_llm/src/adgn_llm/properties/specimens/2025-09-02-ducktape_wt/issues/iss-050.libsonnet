local I = import '../../specimen_issues.libsonnet';

// iss-050: repo_root is a trivial pass-through to get_repo_root
I.issueOneOccurrence(
  id='iss-050',
  rationale='`repo_root` is a trivial pass-through to `get_repo_root`; delete it and make callers call `get_repo_root` instead. Note: the only user is at wt/wt/server/worktree_service.py:221 — update that caller to call `get_repo_root` directly when removing the wrapper.',
  properties=['no-oneoff-vars-and-trivial-wrappers'],
  filesToRanges={
    'wt/wt/server/git_manager.py': [[133, 137]],
    'wt/wt/server/worktree_service.py': [[221, 221]],
  },
)
