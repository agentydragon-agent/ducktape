local I = import '../../lib.libsonnet';

// iss-057: ALLOW case mints two different IDs for same tool call - can't correlate

I.issue(
  rationale=|||
    Lines 164-168 mint TWO different random IDs for the SAME tool call, making it
    impossible to correlate persistence records with in-flight tracking.

    **Current (ALLOW case):**
    Line 164: `await self._record("pg:" + uuid.uuid4().hex, ...)` - ID #1 for persistence
    Line 167: `call_id = uuid.uuid4().hex` - ID #2 for _inflight tracking (no prefix!)
    Line 225: `self._inflight.pop(call_id, None)` - removes using ID #2

    **Problem:** Can't correlate the lifecycle of the same call:
    1. Persistence record uses ID_A ("pg:" prefix)
    2. In-flight tracking uses ID_B (no prefix, different UUID)
    3. When call completes, can't record outcome with same ID used at start
    4. Inconsistent prefix usage (some "pg:", some bare)

    **Compare to ASK case (line 238) - done correctly:**
    Line 238: `call_id = "pg:" + uuid.uuid4().hex` - mints ONCE
    Then uses same `call_id` for: ApprovalHub, notifications, persistence (lines 254, 262)

    **Correct approach:**
    Mint call_id ONCE in common trunk (after decision, before branching), then all paths use it:
    ```python
    # After policy decision
    logger.debug("Policy decision: %s → %s", name, decision, ...)

    # Mint once for all paths
    call_id = "pg:" + uuid.uuid4().hex

    if decision is ALLOW:
        if self._record: await self._record(call_id, ...)
        self._inflight[call_id] = tool_key
        try:
            result = await call_next(context)
        finally:
            self._inflight.pop(call_id, None)

    elif decision is DENY_ABORT:
        if self._record: await self._record(call_id, ...)
        raise ...

    elif decision is DENY_CONTINUE:
        if self._record: await self._record(call_id, ...)
        raise ...

    elif decision is ASK:
        # Use same call_id
        req = ApprovalRequest(...ApprovalToolCall(call_id=call_id, ...))
        ...
    ```

    This eliminates all ID duplication and inconsistency - one mint, all paths use it.
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
