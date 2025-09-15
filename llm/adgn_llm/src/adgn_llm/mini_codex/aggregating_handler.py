from __future__ import annotations

from typing import Any, Iterable

from adgn_llm.mini_codex.loop_control import (
    LoopDecision,
    Continue,
    NoLoopDecision,
    Auto,
    Abort,
    SyntheticAction,
)


# Typed event classes and BaseHandler
from adgn_llm.mini_codex.handler import (
    BaseHandler,
    UserText,
    AssistantText,
    ToolCall,
    FunctionCallOutput,
    Response,
)


class AutoHandler(BaseHandler):
    """Common simple handler that signals Continue(Auto()) for every turn.

    Useful as default handler in simple agents.
    """

    def on_before_sample(self):
        return Continue(Auto())


class AggregatingController:
    """Single controller owning event forwarding and loop-decision semantics.

    Behavior:
      - Handlers are called in registration order. Each handler's
        on_before_sample() is polled; the first concrete LoopDecision wins.
      - If no handler emits a concrete LoopDecision, crash (per requested policy).
      - If multiple handlers emit concrete LoopDecision values that differ,
        crash (conflicting opinions). Only identical decisions across handlers
        would be permitted (but we crash on any conflict per policy).

    This keeps semantics explicit and fails fast on ambiguous or missing
    decision signals.
    """

    def __init__(self, handlers: Iterable[BaseHandler]) -> None:
        self._handlers = list(handlers)

    def on_before_sample(self) -> LoopDecision:  # type: ignore[override]
        # Collect concrete decisions (non-NoLoopDecision) from handlers in order.
        decisions: list[LoopDecision] = []
        for h in self._handlers:
            dec = h.on_before_sample()
            # Explicit deferral must be the NoLoopDecision() sentinel
            if isinstance(dec, NoLoopDecision):
                continue
            # Anything that is not one of the concrete decision classes is a programming error
            if not isinstance(dec, (Continue, Abort, SyntheticAction)):
                raise TypeError(f"Handler {h!r} returned invalid decision type: {type(dec).__name__} ({dec!r})")
            decisions.append(dec)

        # Crash if no handler emitted a decision
        if not decisions:
            raise RuntimeError(
                "No handler emitted a LoopDecision (all returned NoLoopDecision()); crashing per policy."
            )

        # Crash if handlers disagree (any differing decision)
        first = decisions[0]
        for other in decisions[1:]:
            if other != first:
                raise RuntimeError(f"Conflicting handler decisions: {decisions!r}; crashing per policy.")

        return first

    # ---- Event forwarding (typed, observer-only) ----
    def on_response(self, evt: Response) -> None:
        for h in self._handlers:
            h.on_response(evt)

    def on_user_text(self, evt: UserText) -> None:
        for h in self._handlers:
            h.on_user_text_event(evt)

    def on_assistant_text(self, evt: AssistantText) -> None:
        for h in self._handlers:
            h.on_assistant_text_event(evt)

    def on_tool_call(self, evt: ToolCall) -> None:
        for h in self._handlers:
            h.on_tool_call_event(evt)

    def on_function_call_output(self, evt: FunctionCallOutput) -> None:
        for h in self._handlers:
            h.on_function_call_output_event(evt)

    def on_reasoning(self, item: Any) -> None:  # type: ignore[override]
        for h in self._handlers:
            h.on_reasoning(item)
