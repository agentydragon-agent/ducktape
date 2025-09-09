"""Generic loop-control primitives for MiniCodex agents.

This module intentionally avoids application-specific concerns. It exposes a
minimal controller interface to influence the agent loop each sampling step
(e.g., requiring a tool call for the next sampling or aborting the turn).

Policies and decisions are expressed as algebraic types to keep them disjoint
and easy to compose.

Notes / Future work (TODOs):
- Add a RequireSpecific(names: tuple[str, ...]) policy to constrain the next tool
  choice to a known subset once a concrete use case appears.
- Consider optional injection knobs (for debugging only), e.g., synthesizing
  transcript messages or function-call outputs; default off to keep core clean.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from openai.types.responses import (
    ResponseOutput,
    ResponseFunctionToolCall,
    ResponseReasoningItem,
)
from adgn_llm.mini_codex.agent import FunctionCallOutput


# ---------------------------------------------------------------------------
# Tool policy algebraic types (what the model is allowed/required to do next)
# ---------------------------------------------------------------------------


class ToolPolicy:
    """Base class for tool-choice policy."""


@dataclass(frozen=True)
class Auto(ToolPolicy):
    """Let the model decide whether to call a tool or not for the next sample."""


@dataclass(frozen=True)
class RequireAny(ToolPolicy):
    """Require the model to call at least one tool for the next sample."""


@dataclass(frozen=True)
class Forbid(ToolPolicy):
    """Disallow tool calls for the next sample (rarely useful)."""


# Constrained-required policy: require one of specific tool names
# Note: Names should match the function names exposed to the model (e.g.,
# "mcp__prompt_feedback__propose_prompt").
@dataclass(frozen=True)
class RequireSpecific(ToolPolicy):
    names: tuple[str, ...]


# ---------------------------------------------------------------------------
# Loop decision algebraic types (continue vs abort the turn)
# ---------------------------------------------------------------------------


class LoopDecision:
    """Base class for loop decisions returned by the controller."""


@dataclass(frozen=True)
class Continue(LoopDecision):
    tool_policy: ToolPolicy


@dataclass(frozen=True)
class Abort(LoopDecision):
    pass


@dataclass(frozen=True)
class SyntheticAction(LoopDecision):
    """Provide synthetic model output items for this sampling step.

    MiniCodex will skip calling the real LLM for this step and instead process
    these output items (tool calls, assistant messages, reasoning items) as if
    returned by the model. After processing, the loop continues to the next
    sampling step where the controller can return another decision.
    """

    outputs: list[ResponseOutput]


# ---------------------------------------------------------------------------
# Controller protocol and default implementation
# ---------------------------------------------------------------------------


class LoopController(Protocol):
    """Determines next-step loop behavior for MiniCodex agents.

    on_before_sample is invoked once per sampling step. It should return either
    Continue(policy) to proceed, or Abort() to end the current turn.

    Controllers may also implement on_<agent event> hooks; default no-ops are
    provided by BaseLoopController.
    """

    def on_before_sample(self) -> LoopDecision:  # pragma: no cover - interface only
        ...

    def on_user_text(self, text: str) -> None:  # pragma: no cover - interface only
        ...

    def on_assistant_text(self, text: str) -> None:  # pragma: no cover - interface only
        ...

    def on_tool_call(self, call: ResponseFunctionToolCall) -> None:  # pragma: no cover - interface only
        ...

    def on_function_call_output(
        self, call: ResponseFunctionToolCall, output: FunctionCallOutput
    ) -> None:  # pragma: no cover - interface only
        ...

    def on_reasoning(self, item: ResponseReasoningItem) -> None:  # pragma: no cover - interface only
        ...


class BaseLoopController:
    """Base class with no-op agent event hooks.

    Subclass this to conveniently handle on_<agent event> methods without
    affecting core loop control semantics.
    """

    # Loop decision must be implemented by subclasses
    def on_before_sample(self) -> LoopDecision:  # pragma: no cover - interface only
        raise NotImplementedError

    # No-op hooks; subclasses override as needed
    def on_user_text(self, text: str) -> None:  # pragma: no cover - default no-op
        return None

    def on_assistant_text(self, text: str) -> None:  # pragma: no cover - default no-op
        return None

    def on_tool_call(self, call: ResponseFunctionToolCall) -> None:  # pragma: no cover - default no-op
        return None

    def on_function_call_output(
        self, call: ResponseFunctionToolCall, output: FunctionCallOutput
    ) -> None:  # pragma: no cover - default no-op
        return None

    def on_reasoning(self, item: ResponseReasoningItem) -> None:  # pragma: no cover - default no-op
        return None


class DefaultController(BaseLoopController):
    """Default behavior: require a tool on the first sample, then auto.

    Mirrors legacy MiniCodex behavior (first step prefers a tool call, then
    auto). No RequireSpecific here to keep default generic.
    """

    def __init__(self) -> None:
        self._step = 0

    def on_before_sample(self) -> LoopDecision:
        if self._step == 0:
            self._step += 1
            return Continue(RequireAny())
        self._step += 1
        return Continue(Auto())
