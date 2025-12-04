local I = import '../../lib.libsonnet';

// iss-028: Redundant local_runtime None checks after verifying mode is LOCAL

I.issue(
  rationale=|||
    Five functions check both `get_agent_mode(agent_id) != AgentMode.LOCAL` and then
    `get_local_runtime(agent_id) is None`. The second check is redundant - the invariant
    is **mode == LOCAL ⟺ local_runtime is not None**.

    **Evidence:** RunningAgent class (server.py:43) defines `local_runtime: LocalAgentRuntime | None`
    with comment "None for bridge agents". get_local_runtime docstring (server.py:159) says
    "Returns None if agent is not local". register_local_agent (server.py:171-173) always sets
    mode=LOCAL with a local_runtime value.

    **Redundant patterns:**

    Three fully redundant (lines 322-326, 345-349, 367-371):
    ```python
    if registry.get_agent_mode(agent_id) != AgentMode.LOCAL:
        raise ValueError(f"Agent {agent_id} is not a local agent")
    if (local_runtime := registry.get_local_runtime(agent_id)) is None:
        raise ValueError(f"Agent {agent_id} has no local runtime")
    ```
    If mode is LOCAL, local_runtime never None.

    Two partially redundant (lines 561-566, 644-649):
    ```python
    if registry.get_agent_mode(agent_id) != AgentMode.LOCAL:
        raise ValueError(...)
    local_runtime = registry.get_local_runtime(agent_id)
    if local_runtime is None or local_runtime.session is None:  # or .agent is None
        raise ValueError(...)
    ```
    The `local_runtime is None` part is redundant, but `.session/.agent is None` is valid.

    **Fix:**

    Cases 1-3: Remove second check entirely or add assertion.
    Cases 4-5: Remove `local_runtime is None` part, keep field checks:
    ```python
    if registry.get_agent_mode(agent_id) != AgentMode.LOCAL:
        raise ValueError(...)
    local_runtime = registry.get_local_runtime(agent_id)
    if local_runtime.session is None:  # .session/.agent check only
        raise ValueError(...)
    ```

    **Benefits:** Eliminates redundant checks, clearer code, trusts documented invariant,
    simpler error handling.
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
