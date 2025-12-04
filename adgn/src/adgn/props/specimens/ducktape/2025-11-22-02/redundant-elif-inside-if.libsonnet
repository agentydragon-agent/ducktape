local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Confusing "elif live:" inside "if infra:" block (lines 264-267):
    ```python
    if infra:
        # Get pending approvals count
        pending_approvals = len(infra.approval_hub.pending)

        # Derive run phase
        if pending_approvals > 0:
            run_phase = RunPhase.WAITING_APPROVAL
        elif live:  # <-- CONFUSING!
            run_phase = RunPhase.SAMPLING
    ```

    The `elif live:` appears inside `if infra:`, but `live = infra is not None`.
    If we're inside the `if infra:` block, then `live` is always True, making the
    elif test redundant and confusing.

    Should flatten the logic:
    ```python
    if not infra:
        run_phase = RunPhase.IDLE
        pending_approvals = 0
    elif (pending_approvals := len(infra.approval_hub.pending)) > 0:
        run_phase = RunPhase.WAITING_APPROVAL
    else:
        run_phase = RunPhase.SAMPLING
    ```
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/server.py': [[264, 267]],
  },
)
