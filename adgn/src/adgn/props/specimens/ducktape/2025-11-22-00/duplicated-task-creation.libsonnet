local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    The code creates identical tasks (`update_task`, `runner`, and `output_task`) in
    both branches of an if-else, with the runner construction being the only thing
    that differs.

    **Current implementation (cli.py, lines 360-368):**
    ```python
    if passthru and not include_all_from_passthru(passthru):
        precommit_task = asyncio.create_task(run_precommit_wrapper())
        runner = cls(TaskState(ai_task), TaskState(precommit_task), master_fd)
        update_task = asyncio.create_task(runner._update_loop())
        output_task = asyncio.create_task(runner._stream_output(master_fd))
    else:
        # Skip running pre-commit (e.g., --no-verify was passed)
        precommit_task = asyncio.create_task(asyncio.sleep(0))
        runner = cls(TaskState(ai_task), TaskState(precommit_task), None)
        update_task = asyncio.create_task(runner._update_loop())
    ```

    **Problems:**

    1. **Duplication**: `update_task` assignment is identical in both branches
    2. **Missed opportunity**: `runner` construction differs only in the `master_fd`
       parameter (`master_fd` vs `None`)
    3. **Maintenance burden**: Changes to task creation must be duplicated
    4. **Readability**: The similarity obscures what actually differs between branches

    **The correct approach:**

    Move common task creation outside the if-else:

    ```python
    # Determine whether to run pre-commit and set up master_fd accordingly
    if passthru and not include_all_from_passthru(passthru):
        precommit_task = asyncio.create_task(run_precommit_wrapper())
        master_fd_for_runner = master_fd
    else:
        # Skip running pre-commit (e.g., --no-verify was passed)
        precommit_task = asyncio.create_task(asyncio.sleep(0))
        master_fd_for_runner = None

    # Common runner setup
    runner = cls(TaskState(ai_task), TaskState(precommit_task), master_fd_for_runner)
    update_task = asyncio.create_task(runner._update_loop())

    # Only create output_task if we have a master_fd
    if master_fd_for_runner is not None:
        output_task = asyncio.create_task(runner._stream_output(master_fd_for_runner))
    ```

    **Benefits:**

    1. **DRY**: Task creation happens once
    2. **Clearer intent**: The branch decides pre-commit mode and master_fd; task
       creation is separate
    3. **Easier maintenance**: Update task creation in one place
    4. **Less duplication**: Only the varying parts are in the branches
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [360, 368],  // update_task and runner duplication across branches
    ],
  },
)
