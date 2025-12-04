local I = import '../../lib.libsonnet';


I.issue(
  expect_caught_from=[
    ['wt/src/wt/client/wt_client.py'],
    ['wt/src/wt/client/handlers.py'],
  ],
  rationale=|||
    The logic for reading and parsing the daemon PID file is duplicated in two places:
    wt_client.py lines 108-113 (is_daemon_running) and handlers.py lines 250-258 (kill_daemon).
    Both follow the same pattern: async read via `asyncio.to_thread`, strip, check if empty,
    parse int.

    **Why this is problematic:**
    - Same pattern repeated in two locations
    - Changes to PID file format or error handling must update multiple places
    - Risk of inconsistent behavior if one location is updated but not the other
    - Violates DRY principle

    **Fix:** Extract into a shared `async def read_daemon_pid(pid_path: Path) -> int | None`
    helper that handles the read, strip, empty check, and int parse with error handling.
    Returns PID as int if valid, None otherwise. Benefits: single source of truth, easier
    to maintain, consistent error handling, more testable. Note: line 536 in wt_client.py
    also reads the PID file but synchronously for debug output (different requirements,
    fine as-is).
  |||,
  filesToRanges={
    'wt/src/wt/client/wt_client.py': [
      [108, 113],  // Duplicated PID reading in is_daemon_running
    ],
    'wt/src/wt/client/handlers.py': [
      [250, 258],  // Duplicated PID reading in kill_daemon
    ],
  },
)
