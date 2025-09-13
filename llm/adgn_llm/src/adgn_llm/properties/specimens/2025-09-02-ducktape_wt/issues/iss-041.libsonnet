local I = import '../../specimen_issues.libsonnet';

// iss-041: ViewFormatter dead methods
I.issueOccurrencesFromLines(
  rationale='dead code: `_get_sync_column` (L149), `render_worktree_processes`, `render_worktree_removal_progress`, `render_worktree_removal_git_status` — these helpers are unused and should be removed or repurposed.',
  properties=['no-dead-code'],
  linesByFile={
    'wt/wt/client/view_formatter.py': [149, 316, 326, 330],
  },
)
