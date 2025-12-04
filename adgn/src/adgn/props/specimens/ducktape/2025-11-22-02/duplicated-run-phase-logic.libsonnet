local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Run phase determination logic is duplicated across `list_agents()` resource
    (lines 255-267) and `get_agent_info()` resource (lines 296-304).

    Both compute run phase and pending approvals count using identical logic:
    check if infra exists, count pending approvals, decide between IDLE/WAITING_APPROVAL/SAMPLING.

    Should extract a helper method:
    ```python
    def _determine_run_phase(
        self, infra: RunningInfrastructure | None
    ) -> tuple[RunPhase, int]:
        """Determine run phase and pending approvals count."""
        if not infra:
            return RunPhase.IDLE, 0

        pending_approvals = len(infra.approval_hub.pending)
        if pending_approvals > 0:
            return RunPhase.WAITING_APPROVAL, pending_approvals
        else:
            return RunPhase.SAMPLING, pending_approvals
    ```

    Then call it: `run_phase, pending_approvals = self._determine_run_phase(infra)`
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/server.py': [
      [255, 267],
      [296, 304],
    ],
  },
)
