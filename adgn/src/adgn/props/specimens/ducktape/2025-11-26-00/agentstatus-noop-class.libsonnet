local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    AgentStatus is a noop class that should be deleted.

    `AgentStatus` inherits from `AgentStatusCore` but adds nothing - no fields, no methods,
    no config. It's a pure wrapper that serves no purpose.

    **Current implementation:**
    ```python
    class AgentStatus(AgentStatusCore):
        """HTTP response model for agent status; mirrors shared core schema."""
    ```

    The class is used in:
    - Line 266: `response_model=AgentStatus`
    - Line 267: `async def api_agent_status(...) -> AgentStatus:`
    - Line 270: `return AgentStatus(**core.model_dump(mode="json"))`

    The conversion at line 270 is unnecessary - it just dumps and re-parses the same data:
    ```python
    core = await build_agent_status_core(app, agent_id)
    # Re-validate into HTTP schema; dump as JSON-like to coerce enums/inner models
    return AgentStatus(**core.model_dump(mode="json"))
    ```

    **Correct approach:**
    1. Delete the `AgentStatus` class entirely
    2. Replace all uses with `AgentStatusCore`
    3. Simplify line 268-270 to just:
       ```python
       return await build_agent_status_core(app, agent_id)
       ```

    Since `build_agent_status_core` is used in 2 places (app.py:268 and agents_ws.py:191),
    it should NOT be inlined - keep it as a shared function.

    **Benefits:**
    1. Less code - one fewer class
    2. No pointless conversion/re-parsing
    3. Simpler to understand
    4. One less thing to maintain
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/app.py': [
      [58, 60],  // AgentStatus class (noop, delete)
      [266, 266],  // response_model=AgentStatus (use AgentStatusCore)
      [267, 267],  // -> AgentStatus return type (use AgentStatusCore)
      [268, 270],  // Unnecessary conversion (just return await build_agent_status_core)
    ],
  },
)
