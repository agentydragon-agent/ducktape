local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    Line 40 defines `RunningAgent` dataclass with both `mode: AgentMode` and
    `local_runtime: LocalAgentRuntime | None` fields. The mode is completely determined by
    whether local_runtime exists: `mode = BRIDGE` when `local_runtime = None`,
    `mode = LOCAL` when `local_runtime is not None`.

    This is redundant storage. Mode should be derived from local_runtime presence, not stored
    separately. Storing both creates risk of inconsistency (can't get out of sync if mode is
    computed).

    Replace the `mode` field with a property that returns `AgentMode.LOCAL if self.local_runtime
    else AgentMode.BRIDGE`. Update construction sites to omit the mode parameter. Benefits:
    single source of truth, cannot desync, less data to maintain, clear semantic relationship.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/server.py': [
      40,
    ],
  },
)
