local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    When user approves an ASK-case tool call (ContinueDecision at lines 252-258), middleware executes it but does NOT track it in `self._inflight`, making it invisible to `has_inflight_calls()` and `inflight_count()`.

    The ALLOW case (lines 167-225) correctly tracks in _inflight during execution with try/finally cleanup.

    Problems: (1) `has_inflight_calls()` returns False even when ASK-approved call is executing, (2) `inflight_count()` doesn't count ASK-approved calls, (3) can't distinguish "waiting for approval" vs "approved and executing", (4) inconsistent tracking between ALLOW and ASK paths.

    Match the ALLOW pattern: add call to _inflight before execution, clean up in finally block. Both paths should track consistently regardless of whether policy allowed or user approved.
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/policy_gateway/middleware.py': [
      [252, 258],  // ASK → ContinueDecision path missing _inflight tracking
      [167, 225],  // ALLOW path does track (reference for correct pattern)
    ],
  },
)
