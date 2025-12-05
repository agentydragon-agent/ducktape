local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Iteration catches KeyError when agent isn't initialized (lines 245-249):
    ```python
    for agent_id in self.known_agents():
        try:
            mode = self.get_agent_mode(agent_id)
        except KeyError:
            continue
    ```

    This is a code smell indicating poorly structured iteration. We iterate over
    `known_agents()` (returns ALL agent IDs), then call `get_agent_mode()` which
    raises KeyError for uninitialized agents. The mismatch between iteration source
    and accessed data forces the try/except.

    Should iterate over a structure where agent mode is guaranteed to exist:
    ```python
    for agent_id, entry in self._agents.items():
        if entry.agent is None:
            continue  # Skip uninitialized agents
        agent = entry.agent
        infra = agent.running
        # ... rest of logic with guaranteed agent data
    ```

    Or explicitly decide whether to include uninitialized agents with different status.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/server.py': [[245, 249]],
  },
)
