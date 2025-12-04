from __future__ import annotations

from collections.abc import Callable, Iterable
import logging
from typing import Literal

from pydantic import BaseModel

# TODO(mpokorny): Consider supporting ResponseFunctionWebSearch (type="function_web_search")
# as a first-class input item so the agent can initiate web search via Responses
# without custom tool plumbing.
from adgn.agent.events import AssistantText, Response, ToolCall, ToolCallOutput, UserText
from adgn.agent.handler import BaseHandler
from adgn.agent.loop_control import Abort, Compact, InjectItems, LoopDecision, NoAction
from adgn.openai_utils.model import ReasoningItem

logger = logging.getLogger(__name__)


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

    def on_before_sample(self):
        if self._should_abort():
            return Abort()
        return NoAction()


class Reducer:
    """Single reducer owning event forwarding and loop-decision semantics.

    Behavior:
      - Handlers are called in registration order. Each handler's
        on_before_sample() is polled; the first concrete LoopDecision wins.
      - If no handler emits a concrete LoopDecision, crash (per requested policy).
      - If multiple handlers emit concrete LoopDecision values that differ,
        crash (conflicting opinions). Only identical decisions across handlers
        would be permitted (but we crash on any conflict per policy).
    """

    def __init__(self, handlers: Iterable[BaseHandler]) -> None:
        self._handlers = list(handlers)

    def on_before_sample(self) -> LoopDecision:
        """Sequential handler execution: first action wins.

        Handlers are executed in order. The first handler that returns an action
        (InjectItems, Abort, or Compact) wins and we stop processing remaining handlers.

        Actions:
        - InjectItems: inject items (user messages or synthetic output) and process
        - Abort: stop the loop
        - Compact: compact transcript and continue
        - NoAction: defer to next handler (returned by all handlers → sample LLM normally)

        If all handlers defer (return NoAction), we sample the LLM normally.

        Returns:
            LoopDecision from first handler with an action, or NoAction() if all defer
        """
        for h in self._handlers:
            decision = h.on_before_sample()

            # Skip handlers that defer
            if isinstance(decision, NoAction):
                continue

            # Validate decision type
            valid_types = (InjectItems, Abort, Compact)
            if not isinstance(decision, valid_types):
                raise TypeError(
                    f"Handler {h!r} returned invalid decision type: {type(decision).__name__} ({decision!r})"
                )

            # First handler with an action wins
            return decision

        # No handler took action - sample normally
        return NoAction()

    # ---- Event forwarding (typed, observer-only) ----
    def on_response(self, evt: Response) -> None:
        for h in self._handlers:
            h.on_response(evt)

    def on_error(self, exc: Exception) -> None:
        """Forward fatal agent errors to all handlers in registration order."""
        for h in self._handlers:
            h.on_error(exc)

    def on_user_text(self, evt: UserText) -> None:
        for h in self._handlers:
            h.on_user_text_event(evt)

    def on_assistant_text(self, evt: AssistantText) -> None:
        for h in self._handlers:
            h.on_assistant_text_event(evt)

    def on_tool_call(self, evt: ToolCall) -> None:
        for h in self._handlers:
            h.on_tool_call_event(evt)

    # Agent-level before-tool gating removed; Policy Gateway middleware enforces approvals/denials

    def on_tool_result(self, evt: ToolCallOutput) -> None:
        for h in self._handlers:
            h.on_tool_result_event(evt)

    def on_reasoning(self, item: ReasoningItem) -> None:
        for h in self._handlers:
            h.on_reasoning(item)


class SystemMessage(BaseModel):
    role: Literal["system"] = "system"
    content: str
