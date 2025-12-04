local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    `mcp_has_inflight` parameter is always `False` with comments "Tool inflight detection
    is not exposed", making `RunPhase.TOOLS_RUNNING` unreachable. Either implement or remove.

    **Problem: Dead parameter prevents TOOLS_RUNNING state**

    Two call sites (runtime.py:249, status_shared.py:162) pass `mcp_has_inflight=False`.
    The `determine_run_phase()` function checks this parameter but it's always False, so
    `RunPhase.TOOLS_RUNNING` can never be returned.

    **Impact:**
    - Unreachable enum value exists but can't be reached
    - Function signature misleading (suggests inflight detection works)
    - Documentation claims "MCP tools executing" but never happens
    - UI may show wrong phase

    **Decision tree:**

    | Is TOOLS_RUNNING valuable? | Is implementation feasible? | Action |
    |----------------------------|----------------------------|--------|
    | Yes (UI feedback/telemetry) | Yes (can track tool calls) | **Implement** |
    | No or unclear | Any | **Remove** |

    **Option 1: Implement tracking**

    ```python
    class McpManager:
        def __init__(self):
            self._inflight_calls: set[str] = set()

        async def call_tool(...):
            call_id = uuid.uuid4().hex
            self._inflight_calls.add(call_id)
            try:
                return await self._do_call(...)
            finally:
                self._inflight_calls.discard(call_id)

        def has_inflight(self) -> bool:
            return len(self._inflight_calls) > 0

    # In runtime.py:
    has_inflight = self._mcp_manager.has_inflight()  # Actually computed
    ```

    **Option 2: Remove feature**

    ```python
    # Remove TOOLS_RUNNING from RunPhase enum
    # Remove mcp_has_inflight parameter from determine_run_phase()
    def determine_run_phase(*, active_run_id, pending_approvals) -> RunPhase:
        if active_run_id is None: return RunPhase.IDLE
        if pending_approvals > 0: return RunPhase.WAITING_APPROVAL
        return RunPhase.SAMPLING
    ```

    **Principle:** No dead parameters. If a parameter is always constant, either implement
    the varying logic or remove it. Don't keep speculative parameters with hardcoded values.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/runtime.py': [
      [249, 249],   // has_inflight = False with comment "not exposed at this layer"
      [253, 253],   // Passing False to determine_run_phase
    ],
    'adgn/src/adgn/agent/server/status_shared.py': [
      [42, 56],     // determine_run_phase has mcp_has_inflight parameter
      [162, 163],   // has_inflight = False with comment "not exposed here"
    ],
  },
  expect_caught_from=[
    ['adgn/src/adgn/agent/server/runtime.py'],
    ['adgn/src/adgn/agent/server/status_shared.py'],
  ],
)
