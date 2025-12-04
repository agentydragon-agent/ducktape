local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 164-168 mint TWO different random IDs for the SAME tool call, making correlation
    between persistence records and in-flight tracking impossible.

    **The problem:**
    Line 164 creates ID #1 ("pg:" + uuid) for persistence record.
    Line 167 creates ID #2 (bare uuid) for _inflight tracking.
    Line 225 removes using ID #2, breaking the correlation chain.

    Cannot track: persistence → in-flight → completion under a single ID.
    Also inconsistent prefix usage ("pg:" vs bare).

    **Contrast with ASK case (line 238):** Mints call_id ONCE, then uses it consistently
    for ApprovalHub, notifications, and persistence (lines 254, 262).

    **Fix:** Mint call_id once after policy decision, before branching. All paths (ALLOW,
    DENY_ABORT, DENY_CONTINUE, ASK) use the same ID for persistence, tracking, and cleanup.
    This eliminates duplication and ensures consistent prefix usage.
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/policy_gateway/middleware.py': [
      164,  // Throwaway ID for persistence (with "pg:" prefix)
      167,  // Different ID for _inflight (no prefix)
      225,  // Cleanup using second ID - can't correlate with first
      229,  // DENY_ABORT: throwaway ID
      234,  // DENY_CONTINUE: throwaway ID
      238,  // ASK case: correct pattern (mint once, use consistently)
    ],
  },
)
