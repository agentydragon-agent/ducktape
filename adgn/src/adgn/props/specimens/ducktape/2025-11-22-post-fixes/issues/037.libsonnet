local I = import '../../specimens/lib.libsonnet';

// iss-037: RunPhase duplicates and supersedes less comprehensive enums

I.issueOneOccurrence(
  rationale= |||
    Multiple run phase/status enums exist with overlapping but different levels of
    granularity. The most comprehensive version (`RunPhase` in `status_shared.py`)
    should be the canonical representation, replacing less detailed versions.

    **Problem: Multiple run phase enums with different granularity**

    There are at least three run phase/status enums in the codebase:

    **1. status_shared.py RunPhase (most comprehensive):**
    ```python
    class RunPhase(StrEnum):
        IDLE = "idle"
        SAMPLING = "sampling"
        WAITING_TOOL = "waiting_tool"
        TOOLS_RUNNING = "tools_running"
        WAITING_APPROVAL = "waiting_approval"
        SENDING_OUTPUT = "sending_output"
        ERROR = "error"
    ```

    **2. mcp_bridge/types.py RunPhase (less granular):**
    ```python
    class RunPhase(StrEnum):
        """Agent run phase status."""

        IDLE = "idle"
        WAITING_APPROVAL = "waiting_approval"
        SAMPLING = "sampling"
    ```

    **3. protocol.py RunStatus (different granularity, lifecycle-focused):**
    ```python
    class RunStatus(StrEnum):
        IDLE = "idle"
        STARTING = "starting"
        RUNNING = "running"
        AWAITING_APPROVAL = "awaiting_approval"
        ABORTING = "aborting"
        FINISHED = "finished"
        ERROR = "error"
    ```

    **Why this is a problem:**

    1. **Inconsistent granularity**: `status_shared.py` has 7 states, `mcp_bridge/types.py` has 3, `protocol.py` has 7 different ones
    2. **Subset relationships unclear**: Is `mcp_bridge.RunPhase` a projection of `status_shared.RunPhase`?
    3. **Conversion overhead**: Need mapping functions between enums
    4. **Name collision**: Two different `RunPhase` enums
    5. **Missing states**: `mcp_bridge` can't distinguish `TOOLS_RUNNING` from `SAMPLING`
    6. **Lost information**: Less granular enums throw away detail

    **Evidence that status_shared.RunPhase is most comprehensive:**

    It has explicit logic to determine fine-grained states:
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

    This distinguishes `TOOLS_RUNNING` vs `SAMPLING`, which `mcp_bridge` cannot.

    **The correct approach:**

    Use `status_shared.RunPhase` everywhere and delete redundant enums:

    ```python
    # Canonical location: agent/status.py or agent/types.py
    class RunPhase(StrEnum):
        """Agent run phase (fine-grained state machine)."""
        IDLE = "idle"
        SAMPLING = "sampling"
        WAITING_TOOL = "waiting_tool"
        TOOLS_RUNNING = "tools_running"
        WAITING_APPROVAL = "waiting_approval"
        SENDING_OUTPUT = "sending_output"
        ERROR = "error"

    # Delete: mcp_bridge/types.py RunPhase
    # Delete: protocol.py RunStatus (or rename to Lifecycle if it tracks different concern)
    ```

    If `protocol.py` tracks a different dimension (lifecycle: STARTING/FINISHED vs
    execution phase: SAMPLING/TOOLS_RUNNING), rename it to `AgentLifecycle` or merge
    the states appropriately.

    **Migration:**

    Update imports:
    ```python
    # Old:
    from adgn.agent.mcp_bridge.types import RunPhase

    # New:
    from adgn.agent.status import RunPhase  # or from adgn.agent.types
    ```

    Handle missing states:
    ```python
    # If code used 3-state enum, map to comprehensive version:
    def simplified_phase(phase: RunPhase) -> Literal["idle", "waiting_approval", "running"]:
        if phase == RunPhase.IDLE:
            return "idle"
        if phase == RunPhase.WAITING_APPROVAL:
            return "waiting_approval"
        # Collapse all active states to "running"
        return "running"
    ```

    **Why duplication happened:**

    1. `mcp_bridge` was created early with a simple 3-state model
    2. Later, more granular tracking (`TOOLS_RUNNING` vs `SAMPLING`) was needed
    3. `status_shared.py` was added with comprehensive states
    4. Old enum wasn't removed
    5. `protocol.py` may have tracked a different concern (lifecycle) but used similar names

    **Design principle: One enum per dimension, most granular wins**

    - Run phase (execution state): `IDLE`, `SAMPLING`, `TOOLS_RUNNING`, `WAITING_APPROVAL`, `ERROR`
    - Agent lifecycle (availability): `STARTING`, `READY`, `STOPPING`
    - Run outcome (terminal state): `SUCCEEDED`, `FAILED`, `ABORTED`

    Don't create multiple enums for the same dimension with different granularity.
    If you need coarser projections, write mapping functions from the fine-grained enum.

    **Related pattern:**

    If `protocol.RunStatus` tracks lifecycle + phase mixed together, separate them:
    ```python
    class AgentLifecycle(StrEnum):
        STARTING = "starting"
        READY = "ready"
        STOPPING = "stopping"

    class RunPhase(StrEnum):
        IDLE = "idle"
        SAMPLING = "sampling"
        TOOLS_RUNNING = "tools_running"
        WAITING_APPROVAL = "waiting_approval"
        ERROR = "error"

    class RunState(BaseModel):
        lifecycle: AgentLifecycle
        phase: RunPhase
    ```

    Then both dimensions are explicit and independently trackable.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/status_shared.py': [
      [18, 25],   // Most comprehensive RunPhase (7 states)
      [42, 56],   // determine_run_phase with fine-grained logic
    ],
    'adgn/src/adgn/agent/mcp_bridge/types.py': [
      [17, 21],   // Less granular RunPhase (3 states, should be deleted)
    ],
    'adgn/src/adgn/agent/server/protocol.py': [
      [80, 87],   // RunStatus (different granularity, possibly different concern)
    ],
  },
)
