local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Line 53: `global_compositor` parameter is typed as `Compositor | None`, but the server's
    core functionality (creating/deleting agents) depends on having a global compositor to
    mount/unmount agent compositors.

    If None, create_agent (lines 152-159) silently skips mounting. Problems: silent
    degradation, broken invariant (server purpose is to manage agents in global compositor),
    inconsistent state (agent in registry but not mounted), no error feedback, dead code
    path (never happens in practice).

    Server only instantiated in create_global_compositor which always has a compositor.
    No legitimate use case without one.

    Fix: make parameter required (`Compositor` not `Compositor | None`), remove defensive
    None checks in create_agent and delete_agent. Benefits: fail-fast, clear contract,
    simpler code, type safety, correct errors.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/servers/registry_bridge.py': [
      [53, 53],    // Optional global_compositor parameter
      [56, 56],    // Assignment of optional value
      [152, 159],  // Defensive None check in create_agent
      [177, 183],  // Defensive None check in delete_agent
    ],
  },
)
