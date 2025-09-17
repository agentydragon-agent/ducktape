from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from mcp import types as mcp_types

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
    SyntheticAction,
)


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
    """

    def __init__(self, is_done: Callable[[], bool]) -> None:
        self._is_done = is_done

    def on_before_sample(self):  # type: ignore[override]
        if self._is_done():
            return Abort()
        return Continue(RequireAny())


class AggregatingController:
    """Single controller owning event forwarding and loop-decision semantics.

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
        for h in self._handlers:
            dec = h.on_before_sample()
            # Explicit deferral must be the NoLoopDecision() sentinel
            if isinstance(dec, NoLoopDecision):
                continue
            # Anything that is not one of the concrete decision classes is a programming error
            if not isinstance(dec, Continue | Abort | SyntheticAction):
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
        # - Otherwise, prefer a single non-Continue decision if present (e.g., SyntheticAction or Abort)
        # - If multiple differing non-Continue decisions are present -> conflict -> crash
        first = decisions[0]
        if all(d == first for d in decisions):
            return first

        # If all decisions are Continue but not identical, this is a conflict
        if all(isinstance(d, Continue) for d in decisions):
            # decisions differ but all are Continue -> treat as conflict
            raise RuntimeError(
                f"Conflicting Continue decisions from handlers: {decisions!r}",
            )

        # Collect non-Continue decisions (Concrete ones other than Continue)
        non_continue = [d for d in decisions if not isinstance(d, Continue)]
        if len(non_continue) == 0:
            # Fallback: return the first
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
