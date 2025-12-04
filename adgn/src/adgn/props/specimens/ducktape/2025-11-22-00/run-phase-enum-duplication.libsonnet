local I = import '../lib.libsonnet';

// iss-037: RunPhase duplicates and supersedes less comprehensive enums

I.issue(
  snapshot='ducktape/2025-11-22-00',
  rationale= |||
    Three run phase/status enums exist with different granularity. The most comprehensive
    (`status_shared.py` RunPhase) should be canonical, replacing less detailed versions.

    **Problem: Multiple enums with inconsistent granularity**

    | Location | States | Distinguishes TOOLS_RUNNING? |
    |----------|--------|------------------------------|
    | `status_shared.py` RunPhase | 7 (IDLE, SAMPLING, WAITING_TOOL, TOOLS_RUNNING, WAITING_APPROVAL, SENDING_OUTPUT, ERROR) | Yes |
    | `mcp_bridge/types.py` RunPhase | 3 (IDLE, SAMPLING, WAITING_APPROVAL) | No |
    | `protocol.py` RunStatus | 7 (IDLE, STARTING, RUNNING, AWAITING_APPROVAL, ABORTING, FINISHED, ERROR) | No (lifecycle-focused) |

    **Impact:**
    - Name collision (two `RunPhase` enums)
    - Subset relationships unclear
    - Conversion overhead between enums
    - Lost information (coarser enums can't distinguish tool execution from sampling)

    **Evidence for status_shared.RunPhase:**

    The `determine_run_phase()` function (status_shared.py:42-56) has explicit logic to
    distinguish fine-grained states based on run ID, pending approvals, and inflight tools.
    `mcp_bridge` version cannot distinguish `TOOLS_RUNNING` from `SAMPLING`.

    **Solution: Use comprehensive version everywhere**

    ```python
    # Canonical: status_shared.py RunPhase (7 states)
    # Delete: mcp_bridge/types.py RunPhase
    # Rename or merge: protocol.py RunStatus (if lifecycle vs phase distinction needed)
    ```

    If `protocol.RunStatus` tracks a different dimension (lifecycle: STARTING/FINISHED vs
    execution phase: SAMPLING/TOOLS_RUNNING), separate them:

    ```python
    class AgentLifecycle(StrEnum):
        STARTING = "starting"
        READY = "ready"
        STOPPING = "stopping"

    class RunPhase(StrEnum):  # Fine-grained execution state
        IDLE = "idle"
        SAMPLING = "sampling"
        TOOLS_RUNNING = "tools_running"
        WAITING_APPROVAL = "waiting_approval"
        ERROR = "error"
    ```

    For code needing coarser granularity, write mapping functions from fine-grained enum.

    **Principle:** One enum per dimension, most granular wins. Don't create multiple enums
    for the same dimension with different granularity. If coarser projections are needed,
    derive them from the comprehensive version.
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
