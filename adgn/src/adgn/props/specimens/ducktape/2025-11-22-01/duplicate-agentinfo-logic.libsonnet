local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 67-100 (`list_agents`) and 108-135 (`get_agent_info`) duplicate identical logic
    for computing AgentInfo from registry state.

    Duplicated sequence: get mode, get infrastructure, compute live status, initialize
    pending_approvals/run_phase, conditionally count approvals and derive run_phase,
    compute is_local, construct AgentInfo.

    Only difference: error handling (list_agents continues on KeyError, get_agent_info
    raises with message).

    Fix: extract `_compute_agent_info(agent_id) -> AgentInfo` helper that does the
    computation. Simplify both handlers to call the helper with appropriate error handling.

    Benefits: single source of truth, easier testing, reusable, clearer separation.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/servers/registry_bridge.py': [
      [67, 100],   // Duplicated logic in list_agents
      [108, 135],  // Duplicated logic in get_agent_info
    ],
  },
)
