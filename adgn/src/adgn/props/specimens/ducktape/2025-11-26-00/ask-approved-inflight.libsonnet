local I = import '../../lib.libsonnet';

// iss-067: ASK-approved calls not tracked in _inflight during execution

I.issue(
  snapshot='ducktape/2025-11-26-00',
  rationale=|||
    When user approves an ASK-case tool call (ContinueDecision), the middleware executes
    it but does NOT track it in `self._inflight`. This makes it invisible to
    `has_inflight_calls()` and `inflight_count()`.

    **ALLOW case (lines 167-225) - tracks correctly:**
    ```python
    self._inflight[call_id] = tool_key
    try:
        result = await call_next(context)
        ...
    finally:
        self._inflight.pop(call_id, None)
    ```

    **ASK → ContinueDecision case (lines 252-258) - NOT tracked:**
    ```python
    if isinstance(decision_obj, ContinueDecision):
        if self._record: await self._record(call_id, ...)
        try:
            return await call_next(context)  # Executing but not in _inflight!
    ```

    **Problem:**
    1. `has_inflight_calls()` returns False even when ASK-approved call is executing
    2. `inflight_count()` doesn't count ASK-approved executing calls
    3. Can't distinguish "waiting for approval" vs "approved and executing"
    4. Inconsistent tracking between ALLOW and ASK-approved paths

    **Correct approach:**
    Match the ALLOW pattern - track in _inflight during execution:
    ```python
    if isinstance(decision_obj, ContinueDecision):
        if self._record: await self._record(call_id, ...)
        self._inflight[call_id] = tool_key
        try:
            return await call_next(context)
        except McpError as e:
            _raise_if_reserved_code(e, name)
            raise
        finally:
            self._inflight.pop(call_id, None)
    ```

    Now both paths track consistently: any executing call is in _inflight, regardless
    of whether it was ALLOW (policy) or ASK → approved (user).
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/policy_gateway/middleware.py': [
      [252, 258],  // ASK → ContinueDecision path missing _inflight tracking
      [167, 225],  // ALLOW path does track (reference for correct pattern)
    ],
  },
)
