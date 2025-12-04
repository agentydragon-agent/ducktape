local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    Methods `get_agent_mode` (lines 168-177), `get_infrastructure` (lines 158-165), and
    `remove_agent` (lines 224-237) duplicate the same "get agent or raise KeyError" logic.

    Each method: (1) Checks if agent_id in self._agents. (2) Gets self._agents[agent_id].agent.
    (3) Checks if agent is None. (4) Raises KeyError with similar messages. Only difference is
    what field they return (agent.mode vs agent.running) or what they do with the agent.

    Classic code duplication. Extract common helper `_get_agent_or_raise(agent_id) -> RunningAgent`
    that consolidates the lookup logic and raises KeyError if not found/initialized. Then simplify
    all callers to one-liners: `return self._get_agent_or_raise(agent_id).mode`,
    `return self._get_agent_or_raise(agent_id).running`, etc.

    Benefits: DRY - single implementation of lookup logic, consistent error messages, easier to
    maintain. Could even inline some one-liners if called in few places.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/server.py': [
      [158, 165],
      [168, 177],
      [224, 237],
    ],
  },
)
