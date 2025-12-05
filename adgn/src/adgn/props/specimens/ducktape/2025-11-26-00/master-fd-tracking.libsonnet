local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 340-371 create `master_fd_for_runner` variable to pass to runner and
    output_task. This can be refactored to avoid the extra variable.

    **Current:**
    ```python
    if run_precommit:
        ...
        precommit_task = asyncio.create_task(...)
        master_fd_for_runner = master_fd
    else:
        precommit_task = asyncio.create_task(asyncio.sleep(0))
        master_fd_for_runner = None

    runner = cls(..., master_fd_for_runner)
    if master_fd_for_runner is not None:
        output_task = asyncio.create_task(runner._stream_output(master_fd_for_runner))
    ```

    **Simplified:**
    ```python
    if run_precommit:
        ...
        precommit_task = asyncio.create_task(...)
        output_task = asyncio.create_task(runner._stream_output(master_fd))
    else:
        precommit_task = output_task = asyncio.create_task(asyncio.sleep(0))

    runner = cls(..., master_fd if run_precommit else None)
    ```

    No need to track `master_fd_for_runner` separately.
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [340, 371],  // Unnecessary master_fd_for_runner variable
    ],
  },
)
