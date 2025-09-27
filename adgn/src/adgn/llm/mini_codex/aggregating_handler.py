from __future__ import annotations

from collections.abc import Callable, Iterable
import json
import logging
from typing import Any, Literal

from mcp import types as mcp_types
from adgn.llm.openai_utils.model import (
    UserMessage,
)
from pydantic import BaseModel

# TODO(mpokorny): Consider supporting ResponseFunctionWebSearch (type="function_web_search")
# as a first-class input item so the agent can initiate web search via Responses
# without custom tool plumbing.
from adgn.llm.mini_codex.handler import (
    AssistantText,
    BaseHandler,
    BeforeToolCallDecision,
    BypassToolInjectOutput,
    ContinueDecision,
    FunctionCallOutput,
    Response,
    ToolCall,
    UserText,
)
from adgn.llm.mini_codex.loop_control import (
    Abort,
    Auto,
    Continue,
    LoopDecision,
    NoLoopDecision,
    RequireAny,
)

from .mcp_manager import McpManager

logger = logging.getLogger("adgn.mcp")


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

    def __init__(
        self, is_done: Callable[[], bool], defer_when: Callable[[], bool] | None = None
    ) -> None:
        self._is_done = is_done
        self._defer_when = defer_when

    def on_before_sample(self):  # type: ignore[override]
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
        collected_inserts: list[UserMessage] = []
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
                    raise RuntimeError(
                        f"Conflicting skip_sampling flags in Continue decisions: {decisions!r}"
                    )
            # Anything that is not one of the concrete decision classes is a programming error
            if not isinstance(dec, Continue | Abort):
                raise TypeError(
                    f"Handler {h!r} returned invalid decision type: {type(dec).__name__} ({dec!r})",
                )
            decisions.append(dec)

        # Crash if no handler emitted a decision
        if not decisions:
            raise RuntimeError(
                "MiniCodex loop control misconfiguration: no handler emitted a LoopDecision (all returned NoLoopDecision()). "
                "MiniCodex instances must have a configured loop-control handler (that can emit Continue/Abort). "
                "Fix the MiniCodex instance to provide a loop handler.",
            )

        # Reduction rules:
        # - If all decisions are identical -> return that decision
        # - Otherwise, prefer a single non-Continue decision if present (e.g., Abort)
        # - If multiple differing non-Continue decisions are present -> conflict -> crash
        first = decisions[0]
        if all(d == first for d in decisions):
            if isinstance(first, Continue) and collected_inserts:
                return Continue(
                    first.tool_policy,
                    inserts_input=tuple(collected_inserts),
                    skip_sampling=bool(skip_value),
                )
            return first

        # If all decisions are Continue, allow merging when tool_policy matches; else conflict
        if all(isinstance(d, Continue) for d in decisions):
            # All Continue: if tool policies are the same type/value, merge inserts additively
            policies = [d.tool_policy for d in decisions if isinstance(d, Continue)]
            if all(type(p) is type(policies[0]) and p == policies[0] for p in policies):
                return Continue(
                    policies[0],
                    inserts_input=tuple(collected_inserts),
                    skip_sampling=bool(skip_value),
                )
            # Otherwise conflicting Continue opinions
            raise RuntimeError(
                f"Conflicting Continue decisions from handlers: {decisions!r}",
            )

        # Collect non-Continue decisions (Concrete ones other than Continue)
        non_continue = [d for d in decisions if not isinstance(d, Continue)]
        # Mixed case (at least one Continue and at least one non-Continue) is a conflict
        if non_continue and any(isinstance(d, Continue) for d in decisions):
            raise RuntimeError(
                f"Conflicting handler decisions: {decisions!r}; crashing per policy.",
            )
        if len(non_continue) == 0:
            # Fallback: return the first (attach inserts if winning decision is Continue)
            if isinstance(first, Continue) and collected_inserts:
                return Continue(
                    first.tool_policy, inserts_input=tuple(collected_inserts)
                )
            return first
        if len(non_continue) == 1:
            return non_continue[0]

        # Multiple non-Continue decisions: they must be identical or it's a conflict
        first_nc = non_continue[0]
        for other in non_continue[1:]:
            if other != first_nc:
                raise RuntimeError(
                    f"Conflicting handler decisions: {decisions!r}; crashing per policy.",
                )
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

    async def on_before_tool_call(self, evt: ToolCall) -> BeforeToolCallDecision:
        """Ask handlers for a required before-tool-call decision.

        Rules:
        - Call handlers' async before_tool_call(evt) in registration order.
        - Each handler MUST return a BeforeToolCallDecision.
        - If multiple handlers return decisions that differ, crash (conflict).
        - If handlers list is empty, crash.
        """
        decisions: list[BeforeToolCallDecision] = []
        if not self._handlers:
            raise RuntimeError(
                "No handlers registered to make before_tool_call decisions",
            )

        for h in self._handlers:
            # Call each handler's before_tool_call; BaseHandler provides a default ContinueDecision.
            dec = await h.before_tool_call(evt)
            if dec is None:
                # Defensive: shouldn't happen because BaseHandler returns ContinueDecision(), but fail-fast if it does
                raise TypeError(
                    f"Handler {h!r}.before_tool_call returned None; must return a BeforeToolCallDecision",
                )
            # If injecting a result, ensure the result field is the concrete CallToolResult type

            if isinstance(dec, BypassToolInjectOutput) and not isinstance(
                dec.result, mcp_types.CallToolResult
            ):
                raise TypeError(
                    f"Handler {h!r} returned BypassToolInjectOutput with invalid result; result must be an mcp.types.CallToolResult instance",
                )
            decisions.append(dec)

        # Reduction rules:
        # - If all decisions are identical -> return that decision
        # - If there are multiple non-Continue decisions that differ -> conflict (error)
        # - If there is exactly one non-Continue decision and others are ContinueDecision, return the non-Continue one
        first = decisions[0]
        if all(d == first for d in decisions):
            return first

        # Find non-ContinueDecision decisions (type-based, not string matching)

        non_continue = [d for d in decisions if not isinstance(d, ContinueDecision)]
        if len(non_continue) == 0:
            # all continue but not identical (shouldn't happen) -> return first
            return first
        if len(non_continue) == 1:
            return non_continue[0]

        # Multiple non-continue decisions: they must be identical or it's a conflict
        first_nc = non_continue[0]
        for other in non_continue[1:]:
            if other != first_nc:
                raise RuntimeError(
                    f"Conflicting before_tool_call decisions from handlers: {decisions!r}",
                )
        return first_nc

    def on_function_call_output(self, evt: FunctionCallOutput) -> None:
        for h in self._handlers:
            h.on_function_call_output_event(evt)

    def on_reasoning(self, item: Any) -> None:  # type: ignore[override]
        for h in self._handlers:
            h.on_reasoning(item)


class SystemMessage(BaseModel):
    role: Literal["system"] = "system"
    content: str


class NotificationsHandler(BaseHandler):
    """Deliver MCP notifications as one batched system message via Continue.inserts_input.

    Polls McpManager for buffered notifications and, if present, returns a
    Continue(Auto()) decision with a single input-side SystemMessage insert that
    encodes the per-server resource version changes.
    """

    def __init__(self, mcp: McpManager) -> None:
        self._mcp = mcp
        self._msg_counter = 0

    def on_before_sample(self):  # type: ignore[override]
        batch = self._mcp.poll_notifications()
        if not batch.resources_updated:
            logger.debug("NotificationsHandler: no updates")
            return NoLoopDecision()
        # Group by server -> resource_versions
        grouped: dict[str, dict[str, int]] = {}
        for ev in batch.resources_updated:
            resmap = grouped.setdefault(ev.server, {})
            resmap[ev.uri] = ev.version
        payload = json.dumps(
            {
                "servers": {
                    server: {"resource_versions": resmap}
                    for server, resmap in grouped.items()
                }
            }
        )
        self._msg_counter += 1
        # Insert as input-side user message, clearly tagged as a system notification
        tagged = f"<system notification>\n{payload}\n</system notification>"
        msg = UserMessage.text(tagged)
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

    async def on_before_tool_call(self, evt: ToolCall) -> BeforeToolCallDecision:
        # NotificationsHandler does not participate in per-tool decisions; defer
        return ContinueDecision()

    def on_function_call_output(self, evt: FunctionCallOutput) -> None:
        return None

    def on_reasoning(self, item: Any) -> None:  # type: ignore[override]
        return None
