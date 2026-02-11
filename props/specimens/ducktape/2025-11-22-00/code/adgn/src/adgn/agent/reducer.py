from __future__ import annotations

from collections.abc import Callable, Iterable
import logging
from typing import Literal

from pydantic import BaseModel

# TODO(mpokorny): Consider supporting ResponseFunctionWebSearch (type="function_web_search")
# as a first-class input item so the agent can initiate web search via Responses
# without custom tool plumbing.
from adgn.agent.handler import AssistantText, BaseHandler, Response, ToolCall, ToolCallOutput, UserText
from adgn.agent.loop_control import Abort, Auto, Continue, LoopDecision, NoLoopDecision, RequireAny
from adgn.openai_utils.model import (
    AssistantMessageOut,
    FunctionCallItem,
    FunctionCallOutputItem,
    InputItem,
    ReasoningItem,
    UserMessage,
)

from .notifications.types import NotificationsBatch, NotificationsForModel, ResourcesServerNotice

logger = logging.getLogger(__name__)


class AutoHandler(BaseHandler):
    """Common simple handler that signals Continue(Auto()) for every turn.

    Useful as default handler in simple agents.
    """

    def on_before_sample(self):
        return Continue(Auto())


class GateUntil(BaseHandler):
    """Loop controller: require tool call until condition is met, then abort.

    Pass an is_done callable that returns True when the external state indicates
    completion (e.g., submit_state.result is set). While not done, the handler
    enforces RequireAny so the agent keeps making tool calls.

    Optional defer_when: when provided and returns True, this handler defers
    its opinion for this phase (returns NoLoopDecision). Useful to avoid
    conflicts with bootstrap handlers that emit Continue(skip_sampling=True).
    """

    def __init__(self, is_done: Callable[[], bool], defer_when: Callable[[], bool] | None = None) -> None:
        self._is_done = is_done
        self._defer_when = defer_when

    def on_before_sample(self):
        if self._defer_when and self._defer_when():
            return NoLoopDecision()
        if self._is_done():
            return Abort()
        return Continue(RequireAny())


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
        # Collect concrete decisions (non-NoLoopDecision) from handlers in order.
        decisions: list[LoopDecision] = []
        collected_inserts: list[InputItem | FunctionCallItem | FunctionCallOutputItem | AssistantMessageOut] = []
        skip_value: bool | None = None
        for h in self._handlers:
            dec = h.on_before_sample()
            # Explicit deferral must be the NoLoopDecision() sentinel
            if isinstance(dec, NoLoopDecision):
                continue
            # Additive collection of pre-sample inserts_input from Continue decisions
            if isinstance(dec, Continue) and dec.inserts_input:
                collected_inserts.extend(list(dec.inserts_input))
            if isinstance(dec, Continue):
                if skip_value is None:
                    skip_value = dec.skip_sampling
                elif skip_value != dec.skip_sampling:
                    raise RuntimeError(f"Conflicting skip_sampling flags in Continue decisions: {decisions!r}")
            # Anything that is not one of the concrete decision classes is a programming error
            if not isinstance(dec, Continue | Abort):
                raise TypeError(f"Handler {h!r} returned invalid decision type: {type(dec).__name__} ({dec!r})")
            decisions.append(dec)

        # Crash if no handler emitted a decision
        if not decisions:
            raise RuntimeError(
                "MiniCodex loop control misconfiguration: no handler emitted a LoopDecision (all returned NoLoopDecision()). "
                "MiniCodex instances must have a configured loop-control handler (that can emit Continue/Abort). "
                "Fix the MiniCodex instance to provide a loop handler."
            )

        # Reduction rules:
        # - If all decisions are identical -> return that decision
        # - Otherwise, prefer a single non-Continue decision if present (e.g., Abort)
        # - If multiple differing non-Continue decisions are present -> conflict -> crash
        first = decisions[0]
        if all(d == first for d in decisions):
            if isinstance(first, Continue) and collected_inserts:
                return Continue(
                    first.tool_policy, inserts_input=tuple(collected_inserts), skip_sampling=bool(skip_value)
                )
            return first

        # If all decisions are Continue, allow merging when tool_policy matches; else conflict
        if all(isinstance(d, Continue) for d in decisions):
            # All Continue: if tool policies are the same type/value, merge inserts additively
            policies = [d.tool_policy for d in decisions if isinstance(d, Continue)]
            if all(type(p) is type(policies[0]) and p == policies[0] for p in policies):
                return Continue(policies[0], inserts_input=tuple(collected_inserts), skip_sampling=bool(skip_value))
            # Otherwise conflicting Continue opinions
            raise RuntimeError(f"Conflicting Continue decisions from handlers: {decisions!r}")

        # Collect non-Continue decisions (Concrete ones other than Continue)
        non_continue = [d for d in decisions if not isinstance(d, Continue)]
        # Mixed case (at least one Continue and at least one non-Continue) is a conflict
        if non_continue and any(isinstance(d, Continue) for d in decisions):
            raise RuntimeError(f"Conflicting handler decisions: {decisions!r}; crashing per policy.")
        if len(non_continue) == 0:
            # Fallback: return the first (attach inserts if winning decision is Continue)
            if isinstance(first, Continue) and collected_inserts:
                return Continue(first.tool_policy, inserts_input=tuple(collected_inserts))
            return first
        if len(non_continue) == 1:
            return non_continue[0]

        # Multiple non-Continue decisions: they must be identical or it's a conflict
        first_nc = non_continue[0]
        for other in non_continue[1:]:
            if other != first_nc:
                raise RuntimeError(f"Conflicting handler decisions: {decisions!r}; crashing per policy.")
        return first_nc

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


def format_notifications_message(batch: NotificationsBatch) -> UserMessage | None:
    """Format MCP notifications as a system message.

    Returns None if no notifications to format.
    """
    # Use derived per-server list_changed from batch (no magic string checks)
    list_changed_servers = set(batch.resource_list_changed or [])
    if not batch.resources_updated and not list_changed_servers:
        return None

    # Build minimal, non-synthetic payload for the model, grouped by server under "resources".
    # Per-server fields: updated (URIs), list_changed (best effort)
    per_server: dict[str, ResourcesServerNotice] = {}
    for ev in batch.resources_updated:
        entry = per_server.setdefault(ev.server, ResourcesServerNotice())
        entry.updated.append(ev.uri)

    # Mark list_changed for servers recorded in the batch, even if no updated URIs
    for name in list_changed_servers:
        entry = per_server.setdefault(name, ResourcesServerNotice())
        entry.list_changed = True

    # Build minimal per-server map using Pydantic (exclude defaults/empty)
    resources_filtered: dict[str, ResourcesServerNotice] = {
        name: entry for name, entry in per_server.items() if entry.updated or entry.list_changed
    }
    if not resources_filtered:
        return None
    payload = NotificationsForModel(resources=resources_filtered).model_dump_json(
        exclude_defaults=True, exclude_none=True
    )

    # Insert as input-side user message, clearly tagged as a system notification
    tagged = f"<system notification>\n{payload}\n</system notification>"
    return UserMessage.text(tagged)


class NotificationsHandler(BaseHandler):
    """Deliver MCP notifications as one batched system message via Continue.inserts_input.

    Polls a provided notifications buffer for buffered updates and, if present, returns a
    Continue(Auto()) decision with a single input-side SystemMessage insert that
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
            "NotificationsHandler: delivering %d updates (msg #%d)", len(batch.resources_updated), self._msg_counter
        )
        return Continue(Auto(), inserts_input=(msg,))

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

    # Agent-level before-tool gating removed; Policy Gateway middleware enforces approvals/denials

    def on_tool_result(self, evt: ToolCallOutput) -> None:
        return None

    def on_reasoning(self, item: ReasoningItem) -> None:
        return None
