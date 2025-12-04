local I = import '../../lib.libsonnet';


I.issue(
  expect_caught_from=[
    ['adgn/src/adgn/agent/reducer.py'],
    ['adgn/src/adgn/agent/server/mode_handler.py'],
  ],
  rationale=|||
    The function creates an optional UserMessage, then checks if it's None. This is
    backwards - we should decide whether to create a message first, then create it
    unconditionally.

    **Current flow (reducer.py:218-222, mode_handler.py:35-39):**
    1. Unconditionally call `format_notifications_message()` → returns `UserMessage | None`
    2. Check if result is None
    3. Log/handle accordingly

    **Problems:**
    - Creates optional message, then checks for None (backwards logic)
    - `msg` could be inlined into return if message were non-nullable
    - Logging happens at caller, not where we know how many notifications exist

    **Better flow:**
    1. Calculate total notifications count in caller
    2. Log count (or "none")
    3. If zero, return early
    4. Call `format_notifications_message()` → returns non-nullable `UserMessage`
    5. Inline into return

    This makes `format_notifications_message` simpler (always returns message),
    moves logging closer to data source, and enables inlining `msg`.

    **Alternative:** Use walrus operator: `if (msg := format_notifications...) is None:`
    But the above refactor is cleaner overall.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/reducer.py': [
      [218, 222],  // Awkward msg = ...; if msg is None flow
    ],
    'adgn/src/adgn/agent/server/mode_handler.py': [
      [35, 39],  // Same pattern
    ],
  },
)
