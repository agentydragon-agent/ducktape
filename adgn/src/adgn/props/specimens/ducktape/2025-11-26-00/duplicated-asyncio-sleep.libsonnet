local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 314-327 have `await asyncio.sleep(0)` duplicated in both branches. This
    should be on common trunk.

    **Current structure:**
    ```python
    if not readable:
        if self.precommit_state.task.done():
            return
        await asyncio.sleep(0)
        continue
    if not _read_chunk():
        return
    await asyncio.sleep(0)
    ```

    **Simplified:**
    ```python
    if not readable:
        if self.precommit_state.task.done():
            return
    elif not _read_chunk():
        return
    await asyncio.sleep(0)
    ```

    The sleep always happens unless we return early. Factor it to common trunk.
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [314, 327],  // Duplicated asyncio.sleep(0)
    ],
  },
)
