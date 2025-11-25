local I = import '../../specimens/lib.libsonnet';

// iss-017: Redundant "Default: no-op" comments in hook methods

I.issueOneOccurrence(
  rationale= |||
    Several hook methods in `BaseHandler` have multi-line docstrings with "Default: no-op"
    comments, but this is redundant since:
    1. The implementation shows they're no-ops (just `return`)
    2. Base class hook methods are typically no-ops by design
    3. The docstring should focus on what the hook does, not what the default does

    **Current implementation (handler.py, lines 132-182):**
    ```python
    def on_response(self, evt: Response) -> None:
        """Called after receiving a complete model response with usage stats.

        Default: no-op.
        """
        return

    def on_user_text_event(self, evt: UserText) -> None:
        """Called when user text is added to the conversation.

        Default: no-op.
        """
        return

    def on_assistant_text_event(self, evt: AssistantText) -> None:
        """Called when assistant generates text.

        Default: no-op.
        """
        return

    # ... 3 more similar examples ...
    ```

    **Problems:**

    1. **Redundant**: Implementation already shows `return` (no-op)
    2. **Obvious**: Base class hooks are conventionally no-ops
    3. **Verbose**: Extra line adds no information
    4. **Inconsistent**: `on_before_sample` says "Default: no decision" which is more useful
       (explains the return value semantics)

    **The correct approach:**

    Keep one-line docstrings that explain what the hook does, not what the default does:

    ```python
    def on_response(self, evt: Response) -> None:
        """Called after receiving a complete model response with usage stats."""
        return

    def on_user_text_event(self, evt: UserText) -> None:
        """Called when user text is added to the conversation."""
        return

    def on_assistant_text_event(self, evt: AssistantText) -> None:
        """Called when assistant generates text."""
        return
    ```

    For methods that return values, document the return semantics:

    ```python
    def on_before_sample(self) -> LoopDecision:
        """Called before each model sampling step to control loop behavior.

        Returns:
            LoopDecision: Continue | Abort | NoLoopDecision (default: no decision).
        """
        return NoLoopDecision()
    ```

    **When "Default: X" comments ARE useful:**

    - When the default behavior is non-obvious or has side effects
    - When the default differs from what readers might expect
    - When explaining why a particular default was chosen

    Example of useful default comment:
    ```python
    def on_error(self, exc: Exception) -> None:
        """Called when an error occurs during agent execution.

        Default: re-raises the exception. Override to handle gracefully.
        """
        raise exc
    ```

    This is useful because:
    - Re-raising is an action (not a no-op)
    - Readers might expect the error to be logged/swallowed
    - Explains the override contract

    **Benefits of removing redundant comments:**

    1. **Concise**: One-line docstrings are easier to scan
    2. **Focus on contract**: What the hook does, not implementation details
    3. **Less maintenance**: No need to update "Default: X" if implementation changes
    4. **Standard pattern**: Python hooks/callbacks conventionally have no-op defaults
  |||,
  properties=['meaningful-comments', 'remove-noise'],
  filesToRanges={
    'adgn/src/adgn/agent/handler.py': [
      [132, 137],  // on_response: "Default: no-op"
      [149, 154],  // on_user_text_event: "Default: no-op"
      [156, 161],  // on_assistant_text_event: "Default: no-op"
      [163, 168],  // on_tool_call_event: "Default: no-op"
      [170, 175],  // on_tool_result_event: "Default: no-op"
      [177, 182],  // on_reasoning: "Default: no-op"
    ],
  },
  gap_note= |||
    This finding illustrates **"meaningful-comments"** in the context of API documentation:
    docstrings should document the contract (what the method does, parameters, return
    values), not the default implementation.

    For base class hooks/callbacks:
    - Focus on when the hook is called and what it receives
    - Document return value semantics if applicable
    - Don't document that the base implementation is a no-op (that's conventional)

    The base implementation being a no-op is a pattern, not a special case worth documenting.
    Subclasses will override these methods; the docstring helps them understand the contract,
    not the default behavior.

    Related to "remove-noise": implementation details ("Default: no-op") don't belong in
    API documentation. The code itself shows what the default does.
  |||,
)
