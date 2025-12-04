local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Five functions check both `get_agent_mode(agent_id) != AgentMode.LOCAL` and then
    `get_local_runtime(agent_id) is None`. The second check is redundant given the invariant:
    **mode == LOCAL ⟺ local_runtime is not None**.

    Evidence: RunningAgent class (server.py:43) defines `local_runtime: LocalAgentRuntime | None`
    with comment "None for bridge agents"; get_local_runtime docstring says "Returns None if
    agent is not local"; register_local_agent always sets mode=LOCAL with a local_runtime value.

    Lines 322-326, 345-349, 367-371: fully redundant (check mode != LOCAL, then check
    local_runtime is None). If mode is LOCAL, local_runtime is never None.

    Lines 561-566, 644-649: partially redundant (check mode != LOCAL, then check
    `local_runtime is None or local_runtime.session is None`). The `local_runtime is None`
    part is redundant; only the `.session` / `.agent` field checks are valid.

    Remove redundant checks; trust the documented invariant. Benefits: clearer code, simpler
    error handling.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/servers/agents.py': [
      [322, 326],  // agent_state - fully redundant
      [345, 349],  // agent_snapshot - fully redundant
      [367, 371],  // agent_mcp_state - fully redundant
      [561, 566],  // session_state - partially redundant (local_runtime is None part)
      [644, 649],  // abort_agent - partially redundant (local_runtime is None part)
    ],
  },
)
