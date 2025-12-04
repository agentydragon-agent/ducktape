local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The `AgentRuntime` dataclass has `_ui_manager` and `_ui_bus` fields, but `AgentRegistry.create()` sets them after construction instead of passing them to the constructor.

    **Current implementation (registry.py, lines 80-83):**
    ```python
    agent_runtime = AgentRuntime(agent_id=agent_id, running=running, runtime=runtime)
    # Set UI components for backward compatibility
    agent_runtime._ui_manager = conn_mgr_out
    agent_runtime._ui_bus = ui_bus_out
    ```

    **Problems:**
    1. Breaks dataclass contract: Dataclass fields should be set in `__init__`
    2. Confusing comment: "backward compatibility" suggests this is temporary workaround
    3. Type confusion: Fields are nullable but always set after construction
    4. No immutability: Can't use `frozen=True` if setting fields after init

    **Correct approach:**

    Pass all fields to the constructor:
    ```python
    agent_runtime = AgentRuntime(
        agent_id=agent_id,
        running=running,
        runtime=runtime,
        _ui_manager=conn_mgr_out,
        _ui_bus=ui_bus_out,
    )
    ```

    Remove the "backward compatibility" comment since this is the proper way to construct dataclasses.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/runtime/registry.py': [[80, 83]],
  },
)
