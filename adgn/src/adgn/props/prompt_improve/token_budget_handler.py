"""Token budget enforcement handler for prompt improvement agents.

Monitors token consumption and progressively warns the agent as budget is consumed.
Forces prompt submission when budget is exhausted.

Follows same reasoning-detection pattern as CompactionHandler to avoid illegal
tool forcing after reasoning items.
"""

from __future__ import annotations

from enum import Enum, auto
import logging

from adgn.agent.events import AssistantText, ReasoningItem, Response, ToolCall
from adgn.agent.handler import BaseHandler
from adgn.agent.loop_control import Abort, InjectItems, LoopDecision, NoAction
from adgn.openai_utils.model import SystemMessage

logger = logging.getLogger(__name__)


class TokenBudgetState(Enum):
    """Token budget enforcement states."""

    MONITORING = auto()  # 0-50%: Silent tracking
    WARNING_50 = auto()  # 50-90%: Informational notice
    WARNING_90 = auto()  # 90-100%: Urgent warning
    FORCING_SUBMIT = auto()  # 100%+: Force submission
    SUBMITTED = auto()  # Agent successfully submitted
    EXHAUSTED = auto()  # Budget exceeded without submission


class TokenBudgetHandler(BaseHandler):
    """Enforce token budget with progressive warnings and forced submission.

    States:
    - MONITORING (0-50%): Silent tracking
    - WARNING_50 (50-90%): Informational message ("halfway through budget")
    - WARNING_90 (90-100%): Urgent message ("prepare to submit soon")
    - FORCING_SUBMIT (100%+): Inject system message demanding immediate submission
    - SUBMITTED: Agent called submit_prompt
    - EXHAUSTED: Budget exceeded without submission (fallback)

    Token counting:
    - Tracks cumulative tokens from all API responses
    - OpenAI includes reasoning tokens in output_tokens field
    - Uses Response.usage.total_tokens for accuracy

    Reasoning safety:
    - Will not force tool calls immediately after ReasoningItem
    - Waits for next non-reasoning response before injecting messages
    - Follows same pattern as CompactionHandler

    Example:
        handler = TokenBudgetHandler(
            max_tokens=200_000,
            submit_tool_name="prompt_submission_submit_prompt"
        )

        # Handler tracks tokens and injects warnings
        # At 100%: injects SystemMessage forcing submission
        # Agent must call submit_prompt to mark SUBMITTED
    """

    def __init__(self, max_tokens: int, submit_tool_name: str):
        """Initialize token budget handler.

        Args:
            max_tokens: Maximum token budget (e.g., 200_000)
            submit_tool_name: Full MCP tool name for submission (e.g., "prompt_submission_submit_prompt")
        """
        self._max_tokens = max_tokens
        self._submit_tool_name = submit_tool_name
        self._cumulative_tokens = 0
        self._state = TokenBudgetState.MONITORING
        self._last_was_reasoning = False

        logger.info("Initialized: max_tokens=%d, submit_tool=%s", max_tokens, submit_tool_name)

    @property
    def cumulative_tokens(self) -> int:
        """Total tokens consumed so far."""
        return self._cumulative_tokens

    @property
    def state(self) -> TokenBudgetState:
        """Current budget enforcement state."""
        return self._state

    @property
    def percentage_used(self) -> float:
        """Percentage of budget consumed (0.0 to 1.0+)."""
        return self._cumulative_tokens / self._max_tokens

    def mark_submitted(self) -> None:
        """Mark agent as having successfully submitted prompt.

        Called automatically when submit_prompt tool is detected, or manually after
        agent completion to transition to SUBMITTED state. This prevents forced
        submission messages after successful submission.
        """
        logger.info("Marking as SUBMITTED")
        self._state = TokenBudgetState.SUBMITTED

    # ========== Event Handlers ==========

    def on_reasoning(self, item: ReasoningItem) -> None:
        """Track when reasoning items are added to transcript."""
        self._last_was_reasoning = True
        logger.debug("Reasoning item detected, deferring warnings until next response")

    def on_assistant_text_event(self, evt: AssistantText) -> None:
        """Clear reasoning flag when non-reasoning content is added."""
        if self._last_was_reasoning:
            logger.debug("Assistant text after reasoning, warnings now safe")
        self._last_was_reasoning = False

    def on_tool_call_event(self, evt: ToolCall) -> None:
        """Clear reasoning flag when tool calls are added."""
        if self._last_was_reasoning:
            logger.debug("Tool calls after reasoning, warnings now safe")
        self._last_was_reasoning = False

        # Check if agent called submit_prompt
        if evt.name == self._submit_tool_name:
            logger.info("Agent called submit_prompt")
            self.mark_submitted()

    def on_response(self, evt: Response) -> None:
        """Track actual token usage from API responses.

        OpenAI includes reasoning tokens in output_tokens field, so
        total_tokens already includes all token types.
        """
        if evt.usage.total_tokens:
            self._cumulative_tokens += evt.usage.total_tokens
            percentage = 100 * self.percentage_used
            logger.info(
                "Tokens=%d/%d (%.1f%%), state=%s",
                self._cumulative_tokens,
                self._max_tokens,
                percentage,
                self._state.name,
            )

    def on_before_sample(self) -> LoopDecision:
        """Check budget thresholds and inject warnings/force submission.

        State transitions:
        1. MONITORING → WARNING_50 at 50%
        2. WARNING_50 → WARNING_90 at 90%
        3. WARNING_90 → FORCING_SUBMIT at 100%
        4. FORCING_SUBMIT → (stays until SUBMITTED or EXHAUSTED)
        5. SUBMITTED → Abort (terminate agent loop)

        Will not inject messages after ReasoningItem (illegal in OpenAI API).
        """
        pct = self.percentage_used

        # Abort loop if already submitted
        if self._state == TokenBudgetState.SUBMITTED:
            logger.info("Prompt submitted, aborting agent loop")
            return Abort()

        # Defer warnings after reasoning
        if self._last_was_reasoning:
            logger.debug("Deferring warnings (last item is ReasoningItem, pct=%.1f%%)", pct * 100)
            return NoAction()

        # State transitions based on percentage
        if pct >= 1.0:
            # Budget exhausted - force submission
            if self._state != TokenBudgetState.FORCING_SUBMIT:
                logger.warning(
                    "BUDGET EXHAUSTED (%d/%d tokens), forcing submission", self._cumulative_tokens, self._max_tokens
                )
                self._state = TokenBudgetState.FORCING_SUBMIT

            return InjectItems(
                items=[
                    SystemMessage.text(
                        "TOKEN BUDGET EXHAUSTED. You MUST call submit_prompt immediately "
                        "with your current best prompt. The agent will be terminated if you "
                        "do not submit within the next turn."
                    )
                ]
            )

        if pct >= 0.9 and self._state == TokenBudgetState.WARNING_50:
            # Transition to 90% warning
            logger.info("90%% threshold reached, issuing urgent warning")
            self._state = TokenBudgetState.WARNING_90
            return InjectItems(
                items=[
                    SystemMessage.text(
                        f"TOKEN BUDGET WARNING: 90% consumed ({self._cumulative_tokens:,}/{self._max_tokens:,} tokens). "
                        "Prioritize submitting your improved prompt soon. You have approximately "
                        f"{self._max_tokens - self._cumulative_tokens:,} tokens remaining."
                    )
                ]
            )

        if pct >= 0.5 and self._state == TokenBudgetState.MONITORING:
            # Transition to 50% notice
            logger.info("50%% threshold reached, issuing informational notice")
            self._state = TokenBudgetState.WARNING_50
            return InjectItems(
                items=[
                    SystemMessage.text(
                        f"TOKEN BUDGET NOTICE: 50% consumed ({self._cumulative_tokens:,}/{self._max_tokens:,} tokens). "
                        "You have approximately half your budget remaining. Plan your remaining work accordingly."
                    )
                ]
            )

        return NoAction()
