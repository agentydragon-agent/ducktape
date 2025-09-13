local I = import '../../specimen_issues.libsonnet';

// iss-029: No dead code — configuration legacy aliases
I.issueOccurrencesFromLines(
  rationale='Dead legacy aliases: migrate callers and delete: main_repo_resolved, worktrees_dir_resolved, daemon_dir, daemon_socket_file, daemon_pid_file.',
  properties=['no-dead-code'],
  linesByFile={
    'wt/wt/shared/configuration.py': [[92, 116]],
  },
)
