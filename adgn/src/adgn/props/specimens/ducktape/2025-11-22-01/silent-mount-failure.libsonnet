local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    The `create_global_compositor` function (lines 96-103 in compositor_factory.py)
    catches mount errors and continues, creating inconsistent state where some agents
    are accessible and others silently aren't.

    Loop iterates `registry.known_agents()`, tries to mount each compositor, catches
    `Exception`, logs error, and continues. This creates: inconsistent state (some
    mounted, some not), silent failure (logged but system appears healthy), broken
    invariants (registry knows agent but compositor doesn't expose it), 404s when
    accessing unmounted agents (no clear reason why), no recovery path without restart.

    Mount failures indicate serious issues: database corruption, incomplete migration,
    unavailable resources, code bugs. These should prevent startup.

    **Fix:** Remove try/except. Let exceptions propagate; if mount fails, entire
    `create_global_compositor` fails, preventing management UI from starting. Fail-fast
    ensures: clear failure (stack trace points to problem), consistent state (all or
    none), debuggable, forces operator to fix underlying issue before running. Simpler
    code, clearer system health indication.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/compositor_factory.py': [
      [96, 103],   // try/except that silently suppresses mount failures
      [101, 103],  // Error handling that continues instead of failing
    ],
  },
)
