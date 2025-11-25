local I = import '../../specimens/lib.libsonnet';

// iss-039: has_inflight always False indicates unimplemented feature

I.issueOneOccurrence(
  rationale= |||
    The `has_inflight` / `mcp_has_inflight` parameter is always set to `False` with
    comments saying "Tool inflight detection is not exposed", indicating incomplete
    implementation. Either implement the feature or remove the dead parameter.

    **Problem: Parameter exists but is never actually computed**

    Multiple call sites pass `mcp_has_inflight=False` with comments indicating the
    logic doesn't exist.

    **Current implementation (runtime.py, lines 247-253):**
    ```python
    def _current_run_phase(self) -> RunPhase:
        """Current run phase from live approval + inflight status.

        - IDLE: no active run
        - WAITING_APPROVAL: approvals pending
        - TOOLS_RUNNING: MCP tools executing
        - SAMPLING: default while running without approvals or tool exec
        """
        pending = len(self.approval_hub.pending)
        # Tool inflight detection is not exposed at this layer
        has_inflight = False
        return determine_run_phase(
            active_run_id=(self.active_run.run_id if self.active_run else None),
            pending_approvals=pending,
            mcp_has_inflight=has_inflight,
        )
    ```

    **Current implementation (status_shared.py, lines 160-163):**
    ```python
    # Run phase from live signals; no exceptions expected in this path
    # Tool inflight detection is not exposed here; default to False
    has_inflight = False
    run_phase = determine_run_phase(active_run_id=active_run, pending_approvals=pending, mcp_has_inflight=has_inflight)
    ```

    **The determine_run_phase function (status_shared.py, lines 42-56):**
    ```python
    def determine_run_phase(*, active_run_id: UUID | None, pending_approvals: int, mcp_has_inflight: bool) -> RunPhase:
        """Precise run phase from live signals.

        - IDLE: no active run
        - WAITING_APPROVAL: approvals pending
        - TOOLS_RUNNING: MCP manager has in-flight requests
        - SAMPLING: otherwise
        """
        if active_run_id is None:
            return RunPhase.IDLE
        if pending_approvals > 0:
            return RunPhase.WAITING_APPROVAL
        if mcp_has_inflight:
            return RunPhase.TOOLS_RUNNING
        return RunPhase.SAMPLING
    ```

    **Why this is problematic:**

    1. **Dead parameter**: `mcp_has_inflight` is always `False`, so `RunPhase.TOOLS_RUNNING` is never returned
    2. **Misleading code**: Function signature suggests inflight detection works, but it doesn't
    3. **Unreachable states**: `TOOLS_RUNNING` enum value exists but can't be reached
    4. **Documentation lies**: Docstring says "MCP tools executing" but this never happens
    5. **User confusion**: UI might show wrong phase because TOOLS_RUNNING is never set

    **Why this happened:**

    Based on the comments, tool inflight detection was planned but never implemented:
    - "Tool inflight detection is not exposed at this layer"
    - "Tool inflight detection is not exposed here; default to False"

    This suggests the infrastructure to track in-flight tool calls doesn't exist or
    isn't accessible from these call sites.

    **The correct approach: Two options**

    **Option 1: Implement the feature (if needed)**

    Add actual inflight tracking to the MCP compositor/manager:
    ```python
    class McpManager:
        def __init__(self):
            self._inflight_calls: set[str] = set()

        async def call_tool(self, server: str, tool: str, args: dict):
            call_id = uuid.uuid4().hex
            self._inflight_calls.add(call_id)
            try:
                result = await self._do_call(server, tool, args)
                return result
            finally:
                self._inflight_calls.discard(call_id)

        def has_inflight(self) -> bool:
            return len(self._inflight_calls) > 0

    # Then in runtime.py:
    def _current_run_phase(self) -> RunPhase:
        pending = len(self.approval_hub.pending)
        has_inflight = self._mcp_manager.has_inflight()  # Actually computed
        return determine_run_phase(
            active_run_id=(self.active_run.run_id if self.active_run else None),
            pending_approvals=pending,
            mcp_has_inflight=has_inflight,
        )
    ```

    **Option 2: Remove the unimplemented feature (if not needed)**

    If `TOOLS_RUNNING` phase isn't actually needed, simplify:
    ```python
    # Remove TOOLS_RUNNING from enum:
    class RunPhase(StrEnum):
        IDLE = "idle"
        SAMPLING = "sampling"
        WAITING_APPROVAL = "waiting_approval"
        ERROR = "error"
        # Removed: TOOLS_RUNNING (was unreachable)

    # Simplify function:
    def determine_run_phase(*, active_run_id: UUID | None, pending_approvals: int) -> RunPhase:
        """Run phase from active run and approval state."""
        if active_run_id is None:
            return RunPhase.IDLE
        if pending_approvals > 0:
            return RunPhase.WAITING_APPROVAL
        return RunPhase.SAMPLING
    ```

    **How to decide:**

    1. **Is distinguishing TOOLS_RUNNING from SAMPLING valuable?**
       - For UI feedback (showing "Tools executing..." vs "Thinking...")?
       - For telemetry/monitoring?
       - For rate limiting or concurrency control?
    2. **Is implementation feasible?**
       - Can tool calls be tracked from the relevant call sites?
       - Is the MCP manager accessible?
    3. **What's the cost of removing it?**
       - Does the UI depend on `TOOLS_RUNNING`?
       - Are there metrics or logs that reference it?

    If the feature is valuable and implementation is reasonable → implement it.
    If it's not needed or too complex → remove the parameter and enum value.

    **Don't leave it in the current state:**
    - Parameter that's always False
    - Unreachable enum values
    - Comments saying "not implemented"
    - Documentation claiming it works

    **Related issues:**

    This pattern appears in multiple places:
    - `runtime.py` line 249
    - `status_shared.py` line 162

    Both need the same fix (implement or remove).

    **Design principle: No dead parameters**

    If a parameter is always the same value:
    1. Either implement the varying logic
    2. Or remove the parameter and inline the constant

    Don't keep parameters "for future use" with hardcoded values - that's speculative
    code that makes the current behavior unclear.

    Examples:
    ```python
    # Bad: dead parameter
    def foo(x: int, use_cache: bool = True):  # use_cache always True
        # ... never checks use_cache

    # Good: remove it
    def foo(x: int):
        # Always uses cache

    # Or if you want to reserve it:
    def foo(x: int, use_cache: bool = True):
        if not use_cache:
            raise NotImplementedError("Cache bypass not implemented")
        # ... cache logic
    ```
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
)
