from __future__ import annotations

from typing import Any, Iterable

from adgn_llm.mini_codex.loop_control import (
    LoopDecision,
    Continue,
    NoLoopDecision,
    Auto,
)


class BaseHandler:
    """Base handler protocol with no-op implementations.

    Subclass this and override any on_* hooks you need. Implementations must be
    fast and non-blocking. Exceptions should be allowed to propagate so failures
    are loud and visible.
    """

    def on_user_text(self, text: str) -> None:  # default no-op
        return None

    def on_assistant_text(self, text: str) -> None:  # default no-op
        return None

    def on_tool_call(self, call: Any) -> None:  # default no-op
        return None

    def on_function_call_output(self, call: Any, output: Any) -> None:  # default no-op
        return None

    def on_reasoning(self, item: Any) -> None:  # default no-op
        return None

    def on_before_sample(self) -> LoopDecision:
        """Handler-level on_before_sample.

        Return a concrete LoopDecision (Continue/Abort/SyntheticAction) to claim
        the decision for this sampling step, or return NoLoopDecision() to
        explicitly defer. Returning None is forbidden.
        """
        return NoLoopDecision()


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
            # Anything that is not a LoopDecision (by union) is a programming error
            if not isinstance(dec, LoopDecision):
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

    # ---- Event forwarding (observer-only) ----
    def on_user_text(self, text: str) -> None:  # type: ignore[override]
        for h in self._handlers:
            h.on_user_text(text)

    def on_assistant_text(self, text: str) -> None:  # type: ignore[override]
        for h in self._handlers:
            h.on_assistant_text(text)

    def on_tool_call(self, call: Any) -> None:  # type: ignore[override]
        for h in self._handlers:
            h.on_tool_call(call)

    def on_function_call_output(self, call: Any, output: Any) -> None:  # type: ignore[override]
        for h in self._handlers:
            h.on_function_call_output(call, output)

    def on_reasoning(self, item: Any) -> None:  # type: ignore[override]
        for h in self._handlers:
            h.on_reasoning(item)
