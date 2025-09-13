local I = import '../../specimen_issues.libsonnet';

// iss-010: Avoid blanket except Exception in non-boundary code
I.issueOneOccurrence(
  rationale=|||
    Blanket `except Exception:` silently swallows *ANY* `Exception` by just setting `git_paths=[]` and continuing.
    Either:
    - Catch only exact specific expected errors (e.g., Git errors) and scope the try narrowly to the list_worktrees call
    - Or remove the try-catch wrap entirely and just let exceptions crash
  |||,
  properties=['scoped-try-except'],
  filesToRanges={
    'wt/wt/server/wt_server.py': [[1621, 1624]],
  },
)
