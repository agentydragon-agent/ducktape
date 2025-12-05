local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 270-312 manually construct dict objects with 7 fields (id, mode, live, active_run_id,
    run_phase, pending_approvals, capabilities) and serialize via `json.dumps()`, returning `str`.

    Manual dict construction loses: (1) type safety (typos in field names uncaught), (2) validation
    (wrong types or missing fields undetected), (3) IDE support (no autocomplete), (4) self-documentation
    (schema not explicit).

    The rest of the codebase uses Pydantic models for structured responses (e.g., `AgentInfo`,
    `AgentList`, `AgentApprovalsHistory`). This function is an outlier.

    Replace manual dict construction with Pydantic models: define `AgentListItem(BaseModel)` with the
    7 fields, return `AgentsList(agents: list[AgentListItem])` instead of `str`, and remove the manual
    `json.dumps()` call (let the framework handle serialization).
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/servers/agents.py': [
      [261, 312],  // list_agents function with manual dict construction
      [300, 310],  // Dict literal construction
      [312, 312],  // Manual json.dumps() call
    ],
  },
)
