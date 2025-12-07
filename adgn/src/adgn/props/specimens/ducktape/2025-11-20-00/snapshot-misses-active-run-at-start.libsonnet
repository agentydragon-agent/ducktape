local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    AgentSession._run_impl builds and sends a snapshot before setting self.active_run. Line 399
    calls `await self._manager.send_payload(await self.build_snapshot())` but self.active_run isn't
    assigned until line 400-402. Since build_snapshot only includes run metadata when
    self.active_run is non-None, the startup snapshot always contains active_run_id=None, empty
    pending_approvals, and no SnapshotDetails. UI clients reading the snapshot resource never learn
    that a run started until the next snapshot emission (typically at run completion). The
    active_run assignment should be moved before the build_snapshot call so the snapshot accurately
    reflects that a run is active.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/runtime.py': [[399, 402]],
  },
)
