local I = import '../../specimens/lib.libsonnet';

// iss-006: list_agents and get_agent_info duplicate AgentInfo computation logic

I.issueOneOccurrence(
  rationale=|||
    The `list_agents` and `get_agent_info` resource handlers duplicate identical logic
    for computing AgentInfo from registry state (lines 67-100 vs 108-135).

    **Duplicated computation sequence:**
    1. Get mode from registry (`get_agent_mode`)
    2. Get infrastructure (`get_running_infrastructure`)
    3. Compute `live` from `infra is not None`
    4. Initialize `pending_approvals=0`, `run_phase=IDLE`
    5. If infra: count pending approvals, derive run_phase (WAITING_APPROVAL or SAMPLING)
    6. Compute `is_local = mode == AgentMode.LOCAL`
    7. Construct AgentInfo with same field mapping

    **Only difference:** Error handling (list_agents continues on KeyError, get_agent_info
    raises with message).

    **Correct approach:** Extract `_compute_agent_info(agent_id) -> AgentInfo` helper:
    - Gets mode, infrastructure from registry (raises KeyError if not found)
    - Computes live status, pending approvals, run_phase
    - Returns AgentInfo

    Then simplify both handlers:
    ```python
    async def list_agents():
        agents = []
        for agent_id in self._registry.known_agents():
            try:
                agents.append(self._compute_agent_info(agent_id))
            except KeyError:
                continue
        return AgentsListResponse(agents=agents)

    async def get_agent_info(agent_id):
        try:
            return self._compute_agent_info(agent_id)
        except KeyError:
            raise KeyError(f"Agent {agent_id} not found")
    ```

    **Benefits:** Single source of truth, easier testing, reusable for future endpoints,
    clearer separation (handlers do orchestration, helper does computation).
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/servers/registry_bridge.py': [
      [67, 100],   // Duplicated logic in list_agents
      [108, 135],  // Duplicated logic in get_agent_info
    ],
  },
)
