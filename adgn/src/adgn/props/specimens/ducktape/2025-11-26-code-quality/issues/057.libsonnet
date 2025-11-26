local I = import '../../specimens/lib.libsonnet';

// iss-057: Fabricating new random call_id instead of using actual tool call ID

I.issueOneOccurrence(
  rationale=|||
    Lines 166-168 create a new random UUID as `call_id` for tracking in-flight tool calls.
    This appears wrong - it should use the actual call ID from the tool invocation.

    **Current:**
    ```python
    # Track in-flight tool call
    call_id = uuid.uuid4().hex
    self._inflight[call_id] = tool_key
    try:
        call_result = await call_next(context)
        # ... later removed from _inflight ...
    ```

    **Problem:** Fabricating a new random ID means:
    1. The call_id has no relation to the actual MCP tool call ID
    2. Can't correlate tracking with actual call events
    3. Defeats the purpose of tracking - can't look up by real ID

    **Investigation needed:** Check if `context` contains the actual tool call ID.
    If yes, use that instead of generating a new one.

    **Likely fix:**
    ```python
    # Track in-flight tool call using actual call ID
    call_id = context.call_id  # Or however to get it from context
    self._inflight[call_id] = tool_key
    ```

    **If context doesn't have call_id:** Consider whether this tracking is even useful
    without correlation to actual call IDs. Might need to refactor the middleware
    interface to receive call IDs.
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/policy_gateway/middleware.py': [
      [166, 168],  // Fabricating random call_id
    ],
  },
)
