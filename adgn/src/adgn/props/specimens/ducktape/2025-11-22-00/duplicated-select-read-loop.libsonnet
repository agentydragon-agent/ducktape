local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    The `_stream_output` function (cli.py lines 319-330) contains two nearly-identical
    `select-read-sleep` loops differing only in termination condition.

    First loop: reads while task not done. Second loop: drains remaining data (while True).
    Both use identical `select.select([master_fd], [], [], 0.01)`, check `readable`,
    call `_read_chunk()`, and `await asyncio.sleep(0)`.

    **Problems:**
    - Code duplication (pattern repeated with minimal variation)
    - Bug fixes must be applied twice
    - Hard to see what actually differs between loops
    - Missing abstraction opportunity

    **Fix:** Extract helper accepting condition parameter (e.g., `_read_until(master_fd,
    read_chunk, should_continue)`), or unify into single loop with conditional
    termination. Benefits: DRY, clearer intent, single maintenance point, testable
    independently.
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [319, 330],  // Duplicated select-read-sleep loops
    ],
  },
)
