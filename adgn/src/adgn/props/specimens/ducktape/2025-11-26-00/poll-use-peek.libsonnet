local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 62-72 define `poll()` and `peek()` which both call `_build_resources()` and
    create `NotificationsBatch` objects independently. This duplicates the batch creation
    logic.

    **The issue:** Both methods build resources and construct batch objects separately,
    obscuring that `poll()` is conceptually `peek()` plus clear operations.

    **Fix:** Make `poll()` call `peek()`, then clear buffers. This DRYs batch creation
    into one place and makes the relationship explicit: poll = peek + clear.

    If `_build_resources()` becomes single-use after this change, inline it into `peek()`.
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/notifications/buffer.py': [
      [62, 72],  // poll() and peek() both call _build_resources()
    ],
  },
)
