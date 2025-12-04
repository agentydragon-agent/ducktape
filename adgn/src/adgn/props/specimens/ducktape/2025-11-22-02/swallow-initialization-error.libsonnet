local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    Lines 93-95 catch exceptions when mounting agent compositors and continue
    silently with logged error. This is dangerous initialization behavior.

    **Why this is wrong:**
    1. Silent failure: server starts but missing critical infrastructure
    2. Inconsistent state: some agents mounted, others missing
    3. No recovery path: failed agent is simply absent forever
    4. Violates fail-fast: better to crash loudly than fail silently
    5. Debugging nightmare: errors logged but system appears "healthy"

    **Mounting compositors is critical infrastructure.** If it fails, the server
    is misconfigured and should not start.

    **Fix:** Remove try/except entirely. Let exception propagate so server crashes
    during startup, operator sees error immediately, and system never enters
    partially-broken state. Initialization failures should crash.

    If partial mounting is truly needed (unlikely), requires explicit tracking,
    health checks, error APIs, recovery logic, and documentation.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/compositor_factory.py': [
      [93, 95],
    ],
  },
)
