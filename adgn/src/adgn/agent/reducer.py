from __future__ import annotations

from collections.abc import Callable, Iterable
import logging
from typing import Literal

from pydantic import BaseModel

# TODO(mpokorny): Consider supporting ResponseFunctionWebSearch (type="function_web_search")
# as a first-class input item so the agent can initiate web search via Responses
# without custom tool plumbing.
from adgn.agent.handler import AssistantText, BaseHandler, Response, ToolCall, ToolCallOutput, UserText
from adgn.agent.loop_control import Abort, Compact, Continue, InjectItems, LoopDecision, NoLoopDecision
from adgn.openai_utils.model import ReasoningItem, UserMessage

from .notifications.types import NotificationsBatch, ResourcesServerNotice

logger = logging.getLogger(__name__)


class AutoHandler(BaseHandler):
    """Common simple handler that signals Continue() for every turn.

    Useful as default handler in simple agents. Does not inject any items
    or impose constraints - just ensures the loop continues.
    """

    def on_before_sample(self):
        return Continue()


class GateUntil(BaseHandler):
    """Loop controller: continue until condition is met, then abort.

    Pass an is_done callable that returns True when the external state indicates
    completion (e.g., submit_state.result is set).

    Optional defer_when: when provided and returns True, this handler defers
    its opinion for this phase (returns NoLoopDecision). Useful to avoid
    conflicts with bootstrap handlers that emit Continue(skip_sampling=True).

    Note: The agent's tool_policy (typically RequireAnyTool) is configured at
    construction time and applies throughout the agent's lifetime.
    """

    def __init__(self, is_done: Callable[[], bool], defer_when: Callable[[], bool] | None = None) -> None:
        self._is_done = is_done
        self._defer_when = defer_when

    def on_before_sample(self):
        if self._defer_when and self._defer_when():
            return NoLoopDecision()
        if self._is_done():
            return Abort()
        return Continue()


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
        (not NoLoopDecision or empty Continue) wins and we stop processing remaining handlers.

        Actions:
        - InjectItems: inject items (user messages or synthetic output) and process
        - Abort: stop the loop
        - Compact: compact transcript and continue
        - Continue: sample LLM normally (also returned as default if all handlers defer)

        If all handlers defer (return NoLoopDecision or Continue), we sample the LLM normally.

        Returns:
            LoopDecision from first handler with an action, or Continue() if all defer
        """
        for h in self._handlers:
            decision = h.on_before_sample()

            # Skip handlers that defer
            if isinstance(decision, NoLoopDecision):
                continue

            # Validate decision type
            valid_types = (Continue, InjectItems, Abort, Compact)
            if not isinstance(decision, valid_types):
                raise TypeError(
                    f"Handler {h!r} returned invalid decision type: {type(decision).__name__} ({decision!r})"
                )

            # First handler with an action wins
            # InjectItems, Abort, Compact are all actions
            if isinstance(decision, InjectItems | Abort | Compact):
                return decision

            # Continue() passes to next handler (same as NoLoopDecision)

        # No handler did anything - sample normally
        return Continue()

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


def format_notifications_message(batch: NotificationsBatch) -> UserMessage:
    """Format MCP notifications as a user message.

    Caller must ensure batch has at least one notification.
    """
    # Filter to only include servers with actual updates or list changes
    resources_filtered: dict[str, ResourcesServerNotice] = {
        name: entry for name, entry in batch.resources.items() if entry.updated or entry.list_changed
    }

    payload = NotificationsBatch(resources=resources_filtered).model_dump_json(exclude_defaults=True, exclude_none=True)

    # Insert as input-side user message, clearly tagged as a system notification
    return UserMessage.text(f"<system notification>\n{payload}\n</system notification>")


class NotificationsHandler(BaseHandler):
    """Deliver MCP notifications as one batched system message via InjectItems.

    Polls a provided notifications buffer for buffered updates and, if present, returns an
    InjectItems() decision with a single UserMessage that encodes the per-server resource
    version changes.
    """

    def __init__(self, poll: Callable[[], NotificationsBatch]) -> None:
        self._poll = poll
        self._msg_counter = 0

    def on_before_sample(self):
        batch = self._poll()
        notification_count = batch.count_notifications()

        if notification_count == 0:
            logger.debug("NotificationsHandler: no updates")
            return NoLoopDecision()

        self._msg_counter += 1
        logger.info(
            "NotificationsHandler: delivering %d notifications (msg #%d)", notification_count, self._msg_counter
        )
        return InjectItems(items=(format_notifications_message(batch),))
