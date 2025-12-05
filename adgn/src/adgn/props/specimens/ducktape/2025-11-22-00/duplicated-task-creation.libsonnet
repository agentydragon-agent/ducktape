local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    cli.py lines 360-368 create identical tasks (update_task, runner, output_task) in
    both branches of an if-else. Only runner construction differs (master_fd vs None).

    Problems: (1) update_task assignment is duplicated identically in both branches,
    (2) runner construction differs only in the master_fd parameter, (3) changes to
    task creation must be duplicated, (4) similarity obscures what actually differs.

    Move common task creation outside the if-else. The branch should decide
    pre-commit mode and master_fd value; task creation should happen once after.
    Create output_task conditionally only if master_fd is not None.

    Benefits: DRY (task creation happens once), clearer intent (branch decides
    pre-commit mode, task creation is separate), easier maintenance (update in one
    place), less duplication.
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [360, 368],  // update_task and runner duplication across branches
    ],
  },
)
