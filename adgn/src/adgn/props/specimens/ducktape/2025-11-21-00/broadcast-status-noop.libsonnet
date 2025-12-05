local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 223-225 define `broadcast_status` as a no-op with comment "WebSocket status broadcasts
    removed". This is dead code: the method does nothing (explicit pass), the comment confirms
    the functionality was intentionally removed (not temporarily stubbed), and all call sites
    await a no-op wasting cycles.

    Four call sites: line 140 `await self.broadcast_status(True, active)`, line 162 (same),
    line 395 `await self._manager.broadcast_status(True, run_id)`, line 443
    `await self._manager.broadcast_status(True, None)`.

    Delete the method definition and all four call sites. Since it's a no-op, removal has zero
    behavioral change. Keeping dead code creates maintenance burden and confuses readers.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/runtime.py': [
      [223, 225],  // broadcast_status no-op method definition
      [140, 140],  // Call site 1
      [162, 162],  // Call site 2
      [395, 395],  // Call site 3
      [443, 443],  // Call site 4
    ],
  },
)
