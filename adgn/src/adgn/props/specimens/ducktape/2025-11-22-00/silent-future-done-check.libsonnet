local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    approve() and reject() tools in ApprovalHub check if a future is already done,
    but silently ignore this case instead of raising an error.
    If the future is already `.done()`, the code silently:
    - Doesn't set the result
    - Doesn't notify about the problem
    - Returns success status {"status": "approved"}
    - Could mask race conditions or double-approval bugs

    This can happen (for example) if:
    1. User clicks "Approve" twice in quick succession
    2. Two UI clients try to approve the same call_id

    **Why this is bad:**
    1. **Hides bugs** (race conditions or double-processing silently ignored)
    2. **Misleading response**: Returns success when request was not processed
    3. **No visibility**: No log, no error, no way to detect the problem occurred
    4. **Data integrity**: The fact that the future was already resolved might indicate
       a serious bug that should be investigated, not hidden

    **Fix:** Raise an error if the future is already done, or at least return a warning in tool result
    to caller. Same fix needed for reject().

    Benefits of raising:
    - Fail-fast behavior catches bugs early
    - Clear signal that something unexpected happened
    - Prevents silent corruption of approval state
    - Forces callers to handle the race condition properly
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/approvals.py': [
      [185, 189],  // approve() tool - silent ignore if future.done()
      [199, 203],  // reject() tool - silent ignore if future.done()
    ],
  },
)
