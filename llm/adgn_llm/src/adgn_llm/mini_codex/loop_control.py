"""Generic loop-control primitives for MiniCodex agents.

This module intentionally avoids application-specific concerns. It exposes
minimal algebraic types used by handlers to influence the agent loop each
sampling step (e.g., requiring a tool call for the next sampling or aborting
the turn).

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
from typing import TYPE_CHECKING, TypeAlias

if TYPE_CHECKING:
    from openai.types.responses import (
        ResponseOutputMessage,
        ResponseFunctionToolCall,
        ResponseReasoningItem,
    )

    # Union of concrete output item types that the agent processes
    OutputItem: TypeAlias = ResponseReasoningItem | ResponseOutputMessage | ResponseFunctionToolCall


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


@dataclass(frozen=True)
class NoLoopDecision:
    """Explicit null-object sentinel for handler-level on_before_sample.

    Handlers that do not want to claim the LoopDecision MUST return
    NoLoopDecision() rather than None or any other sentinel.
    """


@dataclass(frozen=True)
class Continue:
    tool_policy: ToolPolicy


@dataclass(frozen=True)
class Abort:
    pass


@dataclass(frozen=True)
class SyntheticAction:
    """Provide synthetic model output items for this sampling step.

    MiniCodex will skip calling the real LLM for this step and instead process
    these output items (tool calls, assistant messages, reasoning items) as if
    returned by the model. After processing, the loop continues to the next
    sampling step where handlers can return another decision.
    """

    outputs: list[OutputItem]


# Union type for loop decisions (for static type checking)
LoopDecision: TypeAlias = Continue | Abort | SyntheticAction | NoLoopDecision
