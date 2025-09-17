local I = import '../../specimens/lib.libsonnet';

I.issueOneOccurrence(
  rationale= |||
    Unreachable fallback in get_comprehensive_status(): the function builds and returns a
    WorktreeGitStatus, then a "Fallback: minimal status via GitManager when gitstatusd
    unavailable" block appears immediately after. Because the return is unconditional,
    the fallback block never executes (dead code) and will not handle the
    gitstatusd-unavailable condition as intended.

    Acceptance criteria:
    - Remove the dead fallback block, or restructure logic so the fallback executes only in the
      branch where gitstatusd is unavailable (e.g., place it in the corresponding except/else
      path before the return).
    - Keep a single return path at the end of the branch (or explicit early returns) so
      reachability is clear.
  |||,
  filesToRanges={
    'wt/wt/server/wt_server.py': [[1789, 1844]],
  },
)
