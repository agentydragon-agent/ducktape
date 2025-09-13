local I = import '../../specimen_issues.libsonnet';

// iss-012a: Forbid dynamic attribute access
I.issueOccurrencesFromLines(
  rationale='`getattr(pygit2, "GIT_STATUS_...", 0)` should be plain `pygit2.GIT_STATUS_...`',
  properties=['forbid-dynamic-attrs'],
  linesByFile={
    'wt/wt/server/git_manager.py': [[116, 123]],
    'wt/wt/server/worktree_service.py': [143],
  },
)
