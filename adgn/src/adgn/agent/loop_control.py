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

from adgn.openai_utils.model import FunctionCallItem, UserMessage

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
# use build_mcp_function to compose "prompt_feedback" / "propose_prompt").
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


# Type alias for Continue.inserts_input
# Valid types: UserMessage, FunctionCallItem
# Constraint (enforced at runtime): FunctionCallItem ONLY allowed when skip_sampling=True
# Rationale: FunctionCallItem in normal path would create unresolved function call in API request
InjectableItem = UserMessage | FunctionCallItem


@dataclass(frozen=True)
class Continue:
    """Proceed with the agent loop under a specific tool policy.

    Semantics
    - Normal path (skip_sampling=False):
      - inserts_input are appended to the next Responses API request as-is (input-side items),
        then the model is sampled according to tool_policy.
    - Synthetic path (skip_sampling=True):
      - Do NOT call the model this phase. Instead, treat inserts_input as if they were the
        model's output for this phase (compatibility with the old SyntheticAction).
      - The agent will process these items immediately (e.g., execute any function_call
        via MCP and emit function_call_output), then continue the loop per tool_policy
        on subsequent iterations.

    Compatibility notes (ex-SyntheticAction)
    - Previously, SyntheticAction(outputs=[...]) provided "output-side" items to process locally.
      That behavior is now expressed by Continue(skip_sampling=True, inserts_input=(...)).
    - When skip_sampling=True, inserts_input SHOULD be output-shaped TranscriptItems encoded as
      valid Responses input items (e.g., ResponseFunctionToolCall dicts). The agent will treat
      them as the current phase's resp_output and will NOT send a model request.
    - Do not fabricate server-only rs_/fc_ ids; client-scoped call_id values are acceptable for
      function_call/function_call_output pairs.
    """

    tool_policy: ToolPolicy
    # Items to inject into the agent loop.
    # - Normal path (skip_sampling=False): Must be NormalInjectableItem types, appended to transcript
    # - Skip-sampling path (skip_sampling=True): Must be SyntheticOutputItem types, treated as model output
    # Type annotation accepts the union; caller must ensure items match the skip_sampling mode.
    # ReasoningItem MUST be produced by the SDK/model, never injected.
    inserts_input: tuple[InjectableItem, ...] = ()
    # When True: do NOT call the model this phase; execute directly from inserts_input
    skip_sampling: bool = False


@dataclass(frozen=True)
class Abort:
    pass


# Union type for loop decisions (for static type checking)
type LoopDecision = Continue | Abort | NoLoopDecision
