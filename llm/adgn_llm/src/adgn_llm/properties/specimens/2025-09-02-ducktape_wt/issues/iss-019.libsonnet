local I = import '../../specimen_issues.libsonnet';

// iss-019: Prefer Path/PathLike over str for filesystem paths
I.issueOccurrencesFromLines(
  rationale='Accept Path/PathLike in function signatures and pass Path directly to subprocess/filesystem APIs; avoid str paths.',
  properties=['pathlike'],
  linesByFile={
    'wt/wt/server/git_manager.py': [
      [259, '`path` param of `worktree_add` should be `Path`, not `str`'],
      [297, '`path` param of `worktree_remove` should be `Path`, not `str`'],
    ],
    'wt/tests/integration/test_shell_integration.py': [
      [34, 38, '`run_shell_script` should take `cwd: Path`, not `str`'],
    ],
    'wt/wt/client/wt_client.py': [
      [586, '`identify_worktree` should take `absolute_path: Path`, not `str`'],
    ],
    'wt/wt/server/wt_server.py': [
      [227, '`trigger_refresh` should take `file_path: Path | None`, not `str | None`'],
      [381, 385, '`_should_trigger_refresh` should take `file_path: Path`, not raw `str`. Avoid redundant `str(file_path)`'],
      [2044, 2052, '`_run_post_creation_script_streaming` should take `script_path` as `Path`, not `str`'],
    ],
    'wt/wt/server/worktree_service.py': [
      [299, 'Change signature to: def execute_post_creation_script(script_path: Path, worktree_path: Path) -> dict'],
    ],
  },
)
