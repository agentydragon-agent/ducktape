local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 95-103 in `create_global_compositor` duplicate the mounting logic from
    `mount_agent_compositor_dynamically` (lines 113-130).

    Both do: create agent compositor, mount at `f"agent{agent_id}"`, log. Startup version
    (95-103) wraps in try/except to continue on failure. Dynamic version (113-130) doesn't.

    Problems: maintenance burden (sync changes), inconsistency risk (logic drift), different
    error handling (startup suppresses, dynamic doesn't), different logging messages.

    Fix: call `mount_agent_compositor_dynamically` in the startup loop. Remove try/except
    (see issue 003 for fail-fast rationale). Benefits: single source of truth, consistent
    behavior, less code, uniform error handling.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/compositor_factory.py': [
      [95, 103],    // Duplicated mounting logic
      [113, 130],   // Canonical mount_agent_compositor_dynamically function
    ],
  },
)
