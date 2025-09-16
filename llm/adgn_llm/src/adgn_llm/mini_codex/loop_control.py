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
from typing import TypeAlias

from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
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

    Semantics
    - SyntheticAction tells MiniCodex: "do not call the external LLM for this
      sampling step; instead treat `outputs` as if they were produced by the
      model and process them locally inside the agent loop." This is an
      in‑process primitive used to reduce latency when the action and its tool
      effects can be executed locally.

    fn -> tool -> reasoning pairing
    - When the model normally emits a function_call, the Responses service will
      pair it with an internal reasoning item (rs_...) and a server-side
      function_call id (fc_...). Those server-managed ids/value pairs are
      protected/encrypted and must not be fabricated by clients.
    - If you want to include a function_call in the request input (to replay or
      to bootstrap), do NOT invent rs_/fc_ ids. Instead either:
      * Let the model produce the function_call via `tool_choice` (recommended),
        or
      * Include a client function_call with a client-scoped call_id and also
        include the matching function_call_output produced locally (the agent
        may append a function_call_output object with the same call_id into the
        input so the server sees a tool output for that call). This is the
        supported pattern for "local tool execution then submit the pair": the
        input contains the function_call and the corresponding function_call_output.
    - Do NOT fabricate server-only rs_ or fc_ ids; the API will reject those.

    Testing guidance
    - Live tests: prefer exercising the full flow via `tool_choice` so the model
      and service produce canonical fc_/rs_ pairs.
    - Mocked tests: you may assert on function_call + function_call_output events
      emitted by handlers and the agent. For unit tests that need to simulate a
      real Responses API call, compose input with a function_call plus the
      locally-produced function_call_output (matching call_id) rather than
      inventing rs_ ids.
    - When writing tests, include both variants:
      * live variant that uses tool_choice and validates end-to-end behavior;
      * mocked/unit variant that supplies a synthetic function_call followed by
        the corresponding function_call_output (client-scoped call_id) in the
        agent.messages payload.

    Parametric switch / behavior options
    - Use the agent flag `parallel_tool_calls` and handler-returned SyntheticAction
      to decide whether the model call is skipped and outputs are executed
      locally. SyntheticAction is intended for local execution (no network).
    - If you want to hand control to the model and let the server produce the
      function_call/reasoning pair, use `tool_choice` in the Responses.create
      request instead of SyntheticAction.

    Summary
    - SyntheticAction is an in-process execution primitive: process `outputs`
      locally, do not fabricate server-only reasoning ids, and when submitting
      function_call + tool output to the Responses API, include the tool output
      for the same client call_id rather than inventing rs_* ids.
    """

    outputs: list[OutputItem]


# Union type for loop decisions (for static type checking)
LoopDecision: TypeAlias = Continue | Abort | SyntheticAction | NoLoopDecision
