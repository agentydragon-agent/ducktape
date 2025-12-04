local I = import '../../lib.libsonnet';

// iss-007: Duplicated select-read-sleep loop pattern

I.issue(
  snapshot='ducktape/2025-11-22-00',
  rationale= |||
    The code contains two nearly-identical `select-read-sleep` loops within the same
    function (`_stream_output`), differing only in their termination condition.

    **Current implementation (cli.py, lines 319-330):**
    ```python
    # First loop: while task not done
    while not self.precommit_state.task.done():
        readable, _, _ = select.select([master_fd], [], [], 0.01)
        if readable and not _read_chunk():
            return  # EOF or error
        await asyncio.sleep(0)  # Yield to other tasks

    # Second loop: drain remaining data
    while True:
        readable, _, _ = select.select([master_fd], [], [], 0.01)
        if not readable or not _read_chunk():
            return  # No more data to read
        await asyncio.sleep(0)  # Yield to other tasks
    ```

    **Problems:**

    1. **Code duplication**: The select-read-sleep pattern is repeated with minimal variation
    2. **Maintenance burden**: Bug fixes or improvements must be applied in both places
    3. **Readability**: The similarity makes it hard to see what actually differs
    4. **Missing abstraction**: The pattern could be extracted into a helper

    **The correct approach:**

    Extract the loop pattern into a helper that accepts the condition as a parameter:

    ```python
    async def _read_until(
        self, master_fd: int, read_chunk: Callable[[], bool],
        should_continue: Callable[[], bool]
    ) -> None:
        \"\"\"Read from master_fd while should_continue() returns True.\"\"\"
        while should_continue():
            readable, _, _ = select.select([master_fd], [], [], 0.01)
            if readable and not read_chunk():
                return  # EOF or error
            await asyncio.sleep(0)

    # Usage:
    await self._read_until(
        master_fd, _read_chunk,
        lambda: not self.precommit_state.task.done()
    )
    await self._read_until(
        master_fd, _read_chunk,
        lambda: True  # drain all
    )
    ```

    Or unify into a single loop:
    ```python
    # Read while task running, then drain remaining
    while not self.precommit_state.task.done() or True:
        readable, _, _ = select.select([master_fd], [], [], 0.01)
        if not readable:
            if self.precommit_state.task.done():
                return  # Task done and no more data
            # Task still running, keep checking
            await asyncio.sleep(0)
            continue
        if not _read_chunk():
            return  # EOF or error
        await asyncio.sleep(0)
    ```

    **Benefits:**

    1. **DRY**: Pattern defined once
    2. **Clearer intent**: Different phases are parameterized, not duplicated
    3. **Easier maintenance**: Changes in one place
    4. **Testable**: Helper can be tested independently
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [319, 330],  // Duplicated select-read-sleep loops
    ],
  },
)
