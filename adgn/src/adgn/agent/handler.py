"""Handler interface and decision types for MiniCodex agent loop.

This module defines the BaseHandler interface and loop control decisions.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Literal

from pydantic import BaseModel

from adgn.agent.events import AssistantText, ReasoningItem, Response, ToolCall, ToolCallOutput, UserText
from adgn.agent.loop_control import Abort, LoopDecision, NoAction

__all__ = ["AbortIf", "AbortTurnDecision", "BaseHandler", "ContinueDecision", "SequenceHandler"]


# ----- Generic before-tool-call decision algebra (handler-level, generic) -----


class ContinueDecision(BaseModel):
    """Proceed with normal execution."""

    action: Literal["continue"] = "continue"


class AbortTurnDecision(BaseModel):
    """Request abort of the entire turn."""

    action: Literal["abort"] = "abort"
    reason: str | None = None


class BaseHandler:
    """Base class for agent event handlers with no-op default implementations.

    Subclasses override specific methods to react to agent loop events. All methods
    have sensible defaults so handlers only implement what they need.

    **Contract**:
    - Implementations MUST be fast and non-blocking (use async/await for I/O)
    - Exceptions propagate to the agent loop (fail-fast by default)
    - Return values from hooks influence loop control (e.g., on_before_sample)

    **Common use cases**:
    - Display progress/events to UI (on_user_text_event, on_assistant_text_event)
    - Log transcripts (on_tool_call_event, on_tool_result_event)
    - Control sampling behavior (on_before_sample returns LoopDecision)
    - Persist agent state (on_response)
    """

    def on_error(self, exc: Exception) -> None:
        """Called when the agent encounters a fatal error.

        Default: re-raise exception (fail-fast). Override to log or suppress errors.
        """
        raise exc

    def on_response(self, evt: Response) -> None:
        """Called after receiving a complete model response with usage stats."""
        return

    def on_before_sample(self) -> LoopDecision:
        """Called before each model sampling step to control loop behavior.

        Default: no decision (let other handlers or agent decide).

        Returns:
            LoopDecision: NoAction | InjectItems | Abort | Compact
        """
        return NoAction()

    def on_user_text_event(self, evt: UserText) -> None:
        """Called when user text is added to the conversation."""
        return

    def on_assistant_text_event(self, evt: AssistantText) -> None:
        """Called when assistant generates text."""
        return

    def on_tool_call_event(self, evt: ToolCall) -> None:
        """Called when the model requests a tool call."""
        return

    def on_tool_result_event(self, evt: ToolCallOutput) -> None:
        """Called when a tool call completes and returns a result."""
        return

    def on_reasoning(self, item: ReasoningItem) -> None:
        """Called when the model emits reasoning tokens (extended thinking mode)."""
        return


class SequenceHandler(BaseHandler):
    """Execute a fixed sequence of actions, then NoAction() forever.

    Examples:
        # Inject once
        SequenceHandler([InjectItems(items=(call1, call2))])

        # Inject, sample, then passthrough
        SequenceHandler([InjectItems(...), NoAction()])
    """

    def __init__(self, actions: Sequence[LoopDecision]) -> None:
        self._actions = list(actions)
        self._index = 0

    def on_before_sample(self) -> LoopDecision:
        if self._index >= len(self._actions):
            return NoAction()
        action = self._actions[self._index]
        self._index += 1
        return action


class AbortIf(BaseHandler):
    """Loop controller: abort if condition is met, otherwise continue.

    Pass a should_abort callable that returns True when the agent should stop
    (e.g., submit_state.result is set).

    In the sequential evaluation model, handler ordering matters. Place AbortIf
    after any bootstrap handlers in the handler list to ensure bootstrap completes first.

    Note: The agent's tool_policy (typically RequireAnyTool) is configured at
    construction time and applies throughout the agent's lifetime.
    """

    def __init__(self, should_abort: Callable[[], bool]) -> None:
        self._should_abort = should_abort

    def on_before_sample(self) -> LoopDecision:
        if self._should_abort():
            return Abort()
        return NoAction()
