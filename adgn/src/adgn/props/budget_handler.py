"""Budget enforcement handler for prompt optimization runs.

Monitors cumulative costs across critic/grader runs and enforces budget limits by:
1. Checking if budget is exhausted after each tool result
2. When budget reached: inject final system message and switch to text-only mode
3. Agent produces summary report (detected via on_assistant_text_event)
4. Abort on next sample
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.orm import Session

from adgn.agent.events import AssistantText, ToolCallOutput
from adgn.agent.handler import BaseHandler
from adgn.agent.loop_control import Abort, ForbidAllTools, InjectItems, LoopDecision, NoAction
from adgn.openai_utils.model import UserMessage
from adgn.props.db import get_session, query_builders as qb

logger = logging.getLogger(__name__)


class BudgetEnforcementHandler(BaseHandler):
    """Enforce budget limits for prompt optimization runs.

    Tracks cumulative costs across all critic/grader runs linked to a PO run ID.
    When budget is reached:
    1. Inject system message requesting final summary report
    2. Switch agent to text-only mode (ForbidAllTools)
    3. Allow agent one final turn to produce report
    4. Abort on next sample attempt

    State machine:
    - MONITORING: normal operation, checking budget after each tool result
    - BUDGET_REACHED: injected summary request, waiting for final text response
    - SUMMARY_PRODUCED: got final response, ready to abort
    """

    def __init__(
        self,
        *,
        prompt_optimization_run_id: UUID,
        budget_limit: float,
        agent,  # MiniCodex instance - need reference to mutate tool_policy
    ) -> None:
        self._po_run_id = prompt_optimization_run_id
        self._budget_limit = budget_limit
        self._agent = agent
        self._cumulative_cost: float = 0.0
        self._budget_exhausted = False
        self._summary_requested = False
        self._summary_produced = False

    def _query_total_cost(self, session: Session) -> float:
        """Query total cost from all critic/grader runs for this PO run.

        Uses the po_run_costs query builder and aggregates total_cost column.

        Returns:
            Total cost as float (sum of all run costs)
        """
        # Use existing query builder (joins critic_runs and grader_runs via CTEs)
        query = qb.po_run_costs(self._po_run_id)

        # Execute and sum total_cost column
        result = session.execute(query).fetchall()
        total = sum(row.total_cost for row in result if row.total_cost is not None)

        return float(total)

    def on_tool_result_event(self, evt: ToolCallOutput) -> None:
        """After each tool result, refresh cumulative cost from DB."""
        if self._summary_produced:
            return  # Already done, don't query anymore

        with get_session() as session:
            self._cumulative_cost = self._query_total_cost(session)

        if self._cumulative_cost >= self._budget_limit and not self._budget_exhausted:
            self._budget_exhausted = True
            logger.info(
                f"PO run {self._po_run_id}: Budget exhausted "
                f"(${self._cumulative_cost:.4f} >= ${self._budget_limit:.2f})"
            )

    def on_assistant_text_event(self, evt: AssistantText) -> None:
        """After assistant produces text, check if this is the final summary."""
        if self._summary_requested and not self._summary_produced:
            # Agent produced text response after summary request
            self._summary_produced = True
            logger.info(f"PO run {self._po_run_id}: Summary report produced, will abort on next sample")

    def on_before_sample(self) -> LoopDecision:
        """Enforce budget limits before each sampling step.

        State transitions:
        1. MONITORING → inject summary request when budget reached
        2. BUDGET_REACHED → NoAction (let agent produce final text)
        3. SUMMARY_PRODUCED → Abort
        """
        # State 3: Summary complete, abort
        if self._summary_produced:
            logger.info(f"PO run {self._po_run_id}: Aborting after summary")
            return Abort()

        # State 1: Budget just reached, inject summary request
        if self._budget_exhausted and not self._summary_requested:
            self._summary_requested = True

            # Switch agent to text-only mode
            self._agent._tool_policy = ForbidAllTools()
            logger.info(f"PO run {self._po_run_id}: Switched to text-only mode (ForbidAllTools)")

            # Inject system message requesting final summary
            summary_request = UserMessage.text(f"""**BUDGET EXHAUSTED**

Your budget of ${self._budget_limit:.2f} has been reached.
Cumulative spend: ${self._cumulative_cost:.4f}

Tool calls are now disabled. Produce a final summary report with:

1. **Best prompt found**: prompt SHA256 and key insights
2. **Performance summary**: best recall/precision achieved on valid split
3. **Key learnings**: what worked, what didn't, patterns discovered
4. **Recommendations**: next steps for further optimization

Make this your final response - the session will end after this message.
""")

            return InjectItems(items=[summary_request])

        # State 2 or monitoring: continue normally
        return NoAction()
