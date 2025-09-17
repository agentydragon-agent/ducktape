local I = import '../../specimens/lib.libsonnet';

I.issueOneOccurrence(
  rationale= |||
    Delete --force semantics are broken in two ways:

    1) Force is ignored on the client path:
       - CLI parses `--force` and passes `force` to `handle_remove_worktree`.
       - `remove_worktree(...)` does NOT propagate `force` in the RPC payload; it only sends `wtid`.

    2) Deletion is always forced on the server path:
       - `_handle_worktree_delete_request(...)` unconditionally calls
         `self.git_manager.worktree_remove(str(worktree_path), force=True)` (hard-coded True),
         bypassing safety checks even when the user did NOT pass `--force`.

    Likely intended semantics (value-add over Git):
    - Default (no --force): refuse deletion if either:
      - processes are currently using the worktree directory, or
      - the worktree is not clean (dirty or untracked files).
    - With --force: bypass both gates and remove.
    - Propagate a single boolean `force` end-to-end (CLI → client → protocol → server → git_manager).

    Evidence (specimen paths):
    - wt/wt/cli.py (lines ~215–221): parses `--force` and calls `handle_remove_worktree(config, name, force)`.
    - wt/wt/client/worktree_utils.py (lines ~146–174): `remove_worktree(...)` resolves WorktreeID and calls
      `daemon_client.delete_worktree(target_wtid)` — `force` is NOT sent over RPC.
    - wt/wt/server/wt_server.py (lines ~2092–2116): `_handle_worktree_delete_request(...)` validates, then calls
      `self.git_manager.worktree_remove(str(worktree_path), force=True)` (hard-coded True regardless of user intent),
      then rmtree.
    - Contrast (intended gating): wt/wt/server/worktree_service.py (lines ~166–196) checks for processes-in-use and
      cleanliness when not forced, and passes `force=force` to git_manager.

    Acceptance criteria:
    - Protocol: add `force: bool` to `WorktreeDeleteParams`.
    - Client: propagate `force` through `remove_worktree → daemon_client.delete_worktree(..., force)`.
    - Server handler: respect the provided `force`; when not forced, perform the two gates (process-in-use and
      cleanliness) before deletion and fail with a clear message if either gate triggers; when forced, bypass gates.
    - Only pass `force=True` to `git_manager.worktree_remove(...)` when the user requested `--force`; otherwise pass
      `force=False`.
  |||,
  filesToRanges={
    'wt/wt/cli.py': [[215, 221]],
    'wt/wt/client/worktree_utils.py': [[146, 174]],
    'wt/wt/server/wt_server.py': [[2092, 2116]],
    'wt/wt/server/worktree_service.py': [[166, 196]],
  },
)
