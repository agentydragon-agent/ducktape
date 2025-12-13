"""Budget enforcement handler for prompt optimization runs.

Monitors cumulative costs across critic/grader runs and enforces budget limits by:
1. Checking if budget is exhausted after each tool result
2. When budget reached: inject final system message and switch to text-only mode
3. Agent produces summary report (detected via on_assistant_text_event)
4. Abort on next sample
"""

from __future__ import annotations

from enum import StrEnum
import logging
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.orm import Session

from adgn.agent.events import AssistantText
from adgn.agent.handler import BaseHandler
from adgn.agent.loop_control import Abort, ForbidAllTools, InjectItems, LoopDecision, NoAction
from adgn.openai_utils.model import UserMessage
from adgn.props.db import get_session, query_builders as qb

if TYPE_CHECKING:
    from adgn.agent.agent import Agent

logger = logging.getLogger(__name__)


class BudgetState(StrEnum):
    """Budget enforcement state machine states."""

    MONITORING = "monitoring"
    SUMMARY_REQUESTED = "summary_requested"
    SUMMARY_PRODUCED = "summary_produced"


# TextMessageRedirectHandler moved to adgn.agent.handler.RedirectOnTextMessageHandler


class BudgetEnforcementHandler(BaseHandler):
    """Enforce budget limits for prompt optimization runs.

    Tracks cumulative costs across all critic/grader runs linked to a PO run ID.
    When budget is reached:
    1. Inject system message requesting final summary report
    2. Switch agent to text-only mode (ForbidAllTools)
    3. Allow agent one final turn to produce report
    4. Abort on next sample attempt

    State machine:
    - MONITORING: normal operation, checking budget before each sample
    - SUMMARY_REQUESTED: budget exceeded, injected summary request, waiting for final text response
    - SUMMARY_PRODUCED: got final response, ready to abort
    """

    def __init__(
        self,
        *,
        prompt_optimization_run_id: UUID,
        budget_limit: float,  # USD
        agent: Agent,
    ) -> None:
        self._po_run_id = prompt_optimization_run_id
        self._budget_limit = budget_limit
        self._agent = agent
        self._state = BudgetState.MONITORING

    def _query_total_cost(self, session: Session) -> float:
        """Query total cost from all critic/grader runs for this PO run.

        Uses the po_run_costs query builder and aggregates cost_usd column.

        Returns:
            Total cost as float (sum of all run costs)
        """
        query = qb.po_run_costs(self._po_run_id)

        # Execute and sum cost_usd column
        result = session.execute(query).fetchall()
        total: float = sum(row.cost_usd for row in result if row.cost_usd is not None)
        return total

    def on_assistant_text_event(self, evt: AssistantText) -> None:
        """After assistant produces text, check if this is the final summary."""
        if self._state == BudgetState.SUMMARY_REQUESTED:
            # Agent produced text response after summary request
            self._state = BudgetState.SUMMARY_PRODUCED
            logger.info(f"PO run {self._po_run_id}: Summary report produced, will abort on next sample")

    def on_before_sample(self) -> LoopDecision:
        """Enforce budget limits before each sampling step.

        State transitions:
        1. SUMMARY_PRODUCED → Abort
        2. MONITORING with budget exceeded → inject summary request, transition to SUMMARY_REQUESTED
        3. SUMMARY_REQUESTED → NoAction (waiting for response)
        4. MONITORING with budget OK → NoAction
        """
        # State: Summary complete, abort
        if self._state == BudgetState.SUMMARY_PRODUCED:
            logger.info(f"PO run {self._po_run_id}: Aborting after summary")
            return Abort()

        # State: Monitoring - check budget before sampling
        if self._state == BudgetState.MONITORING:
            with get_session() as session:
                cumulative_cost = self._query_total_cost(session)

            if cumulative_cost >= self._budget_limit:
                logger.info(
                    f"PO run {self._po_run_id}: Budget exhausted (${cumulative_cost:.4f} >= ${self._budget_limit:.2f})"
                )
                self._state = BudgetState.SUMMARY_REQUESTED

                # Switch agent to text-only mode
                self._agent._tool_policy = ForbidAllTools()
                logger.info(f"PO run {self._po_run_id}: Switched to text-only mode (ForbidAllTools)")

                # Inject system message requesting final summary
                summary_request = UserMessage.text(
                    f"""\
Your budget of ${self._budget_limit:.2f} has been exceeded.
Tool calls are now disabled. Produce a final summary report with:

1. **Best prompt found**: prompt SHA256 and key insights
2. **Performance summary**: best recall achieved on valid split
3. **Key learnings**: what worked, what didn't, patterns discovered
4. **Recommendations**: next steps for further optimization

Make this your final response - the session will end after this message.
"""
                )

                return InjectItems(items=[summary_request])

        # State: Waiting for summary response or budget still OK
        return NoAction()
