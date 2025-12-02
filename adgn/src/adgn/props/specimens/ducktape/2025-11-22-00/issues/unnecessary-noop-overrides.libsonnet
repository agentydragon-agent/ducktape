local I = import '../../specimens/lib.libsonnet';

// iss-018: Unnecessary no-op method overrides in NotificationsHandler

I.issueOneOccurrence(
  rationale= |||
    `NotificationsHandler` explicitly implements 7 no-op methods (lines 244-265) that
    just `return None`, but these are already provided by `BaseHandler`. There's no
    need to override methods that do nothing different from the base implementation.

    **Current implementation (reducer.py, lines 217-265):**
    ```python
    class NotificationsHandler(BaseHandler):
        """Deliver MCP notifications as one batched system message."""

        def __init__(self, poll: Callable[[], NotificationsBatch]) -> None:
            self._poll = poll
            self._msg_counter = 0

        def on_before_sample(self):
            # ... actual implementation that returns Continue or NoLoopDecision ...

        # ---- Event forwarding (typed, observer-only) ----
        def on_response(self, evt: Response) -> None:
            return None

        def on_error(self, exc: Exception) -> None:
            return None

        def on_user_text(self, evt: UserText) -> None:
            return None

        def on_assistant_text(self, evt: AssistantText) -> None:
            return None

        def on_tool_call(self, evt: ToolCall) -> None:
            return None

        def on_tool_result(self, evt: ToolCallOutput) -> None:
            return None

        def on_reasoning(self, item: ReasoningItem) -> None:
            return None
    ```

    **Problems:**

    1. **Unnecessary code**: Base class already provides these no-ops
    2. **Maintenance burden**: Must keep these in sync if base class changes
    3. **False signal**: Suggests these methods do something different from base
    4. **Verbose**: 7 methods × 3 lines = 21 lines of no-op code
    5. **Misleading comment**: "Event forwarding (typed, observer-only)" suggests
       they forward/observe, but they just return None like the base

    **The correct approach:**

    Remove all the no-op overrides:

    ```python
    class NotificationsHandler(BaseHandler):
        """Deliver MCP notifications as one batched system message via Continue.inserts_input.

        Polls a provided notifications buffer for buffered updates and, if present, returns a
        Continue(AllowAnyToolOrTextMessage()) decision with a single input-side SystemMessage insert that
        encodes the per-server resource version changes.
        """

        def __init__(self, poll: Callable[[], NotificationsBatch]) -> None:
            self._poll = poll
            self._msg_counter = 0

        def on_before_sample(self):
            batch = self._poll()
            msg = format_notifications_message(batch)

            if msg is None:
                logger.debug("NotificationsHandler: no updates")
                return NoLoopDecision()

            self._msg_counter += 1
            logger.info(
                "NotificationsHandler: delivering %d updates (msg #%d)",
                len(batch.resources_updated),
                self._msg_counter
            )
            return Continue(AllowAnyToolOrTextMessage(), inserts_input=(msg,))

        # That's it - no need to override no-op methods!
    ```

    **Benefits:**

    1. **Concise**: 21 fewer lines of code
    2. **Clear intent**: Only overrides what matters (`on_before_sample`)
    3. **Maintainable**: No need to track base class changes
    4. **Standard pattern**: Subclasses override only what they need
    5. **Self-documenting**: Missing overrides signal "uses base behavior"

    **When to override no-op methods:**

    Only override if you're doing something different:
    - Logging/debugging (but consider a decorator instead)
    - Validation/assertions
    - Side effects (state updates, metrics)
    - Different return values

    Don't override to return the same value the base returns.

    **General principle:**

    In object-oriented programming with base class hooks/callbacks:
    - Base class provides sensible defaults (often no-ops)
    - Subclasses override only what they need to specialize
    - Empty overrides are code smell (either do something or don't override)
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/reducer.py': [
      [244, 265],  // 7 unnecessary no-op method overrides
    ],
  },
)
