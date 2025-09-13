local I = import '../../specimens/lib.libsonnet';

// iss-034: Early bailout — invert guard in process_single_worktree
I.issueOneOccurrence(
  rationale=|||
    In `process_single_worktree`, invert the guard to early-bail when `gs_client` is missing and keep the happy path flat. Extracting the branch into a helper improves readability and reduces nesting.

    Before (shape):
    ```python
    if gs_client:
        ...  # big branch
    else:
        ...  # small branch
    ```

    After (refactor sketch):
    ```python
    def _compute_single_status(worktree_path: Path, gs_client) -> WorktreeGitStatus:
        if not gs_client:
            return WorktreeGitStatus(
                state="stopped",
                dirty_files=[],
                untracked_files=[],
                ...,
            )
        # happy path (cache, bounded refresh, meta + PR fetch)
        ...

    # in process_single_worktree
    single_start = time.time()
    gs_client = self.gitstatusd_clients.get(worktree_path)
    status = _compute_single_status(worktree_path, gs_client)
    individual_times[worktree_path] = (time.time() - single_start) * 1000
    return status
    ```

    This makes the happy path obvious and enables measuring/isolating the per-worktree timing more cleanly.
  |||,
  // properties=['early-bailout', 'minimize-nesting'],
  filesToRanges={
    'wt/wt/server/wt_server.py': [[1648, 1660]],
  },
)
