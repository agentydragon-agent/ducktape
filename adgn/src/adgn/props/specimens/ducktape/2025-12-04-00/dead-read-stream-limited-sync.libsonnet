local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The function `read_stream_limited_sync()` at lines 241-264 is dead code that is never called anywhere in the codebase. A ripgrep search across the entire project shows only the function definition itself, with no call sites.

    The async variant `read_stream_limited_async()` (lines 266+) is actively used in `seatbelt.py` for reading subprocess stdout/stderr streams. The sync version appears to be leftover or speculative code that was never integrated into any actual execution paths.

    Docker exec implementations (`_run_session_container` and `_run_ephemeral_container`) use different approaches (custom stream reading from `exec_obj.start()` and `container.log()` API respectively), not the generic stream reader functions.

    This function should be removed.
  |||,
  filesToRanges={'adgn/src/adgn/mcp/exec/models.py': [[241, 264]]},
)
