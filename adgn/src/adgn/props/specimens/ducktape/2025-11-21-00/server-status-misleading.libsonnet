local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 197-201 define `ServerStatus` enum with docstring "Agent server runtime status" and values
    `RUNNING`/`STOPPED`. Line 216 includes `status: ServerStatus` field in `AgentInfoDetailed` model.

    This is misleading: name suggests server status, but actually tracks local agent status (not server).
    For remote agents (`mode == AgentMode.REMOTE`), neither "running" nor "stopped" are semantically
    correct (we don't know if remote agent is running, and "stopped" implies control we don't have).
    Status confuses local infrastructure availability with agent operational state. Unclear semantics:
    does "running" mean process running, infrastructure loaded, processing request, or registered?

    Resolution unclear per user ("no way this field isn't misleading"). Possible approaches: replace
    with `infrastructure_available: bool` for local infrastructure status, use mode-specific optional
    field `local_infrastructure_running: bool | None` (only for LOCAL mode), or remove entirely if
    inferable from other queries. Needs redesign for clearer semantics and correct remote agent modeling.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/servers/agents.py': [
      [197, 201],  // ServerStatus enum with misleading name
      [216, 216],  // AgentInfoDetailed.status field
      [198, 198],  // Misleading docstring "Agent server runtime status"
    ],
  },
)
