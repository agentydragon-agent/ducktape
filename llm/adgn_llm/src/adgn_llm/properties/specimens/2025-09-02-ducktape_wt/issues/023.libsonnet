local I = import '../../specimens/lib.libsonnet';

// iss-023: Prefer comprehensions over for+append
I.issueOneOccurrence(
  rationale=|||
    Replace for+append loop with a list comprehension. It's shorter, more expressive and takes less units of state.

    Before:
    ```python
    for wtid in worktree_ids:
        worktree_name = parse_worktree_id(wtid)
        worktree_path = self.config.worktrees_dir / worktree_name
        worktree_paths.append(worktree_path)
    ```

    After:
    ```python
    worktree_paths = [
        self.config.worktrees_dir / parse_worktree_id(wtid)
        for wtid in worktree_ids
    ]
    ```
  |||,
  // properties=[],
  filesToRanges={
    'wt/wt/server/wt_server.py': [[1610, 1614]],
  },
  gap_note='GAP: Prefer comprehensions for simple constructions over loops with append when readable.',
)
