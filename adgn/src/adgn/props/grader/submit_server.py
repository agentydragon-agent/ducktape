"""MCP server for grader submit workflow.

Provides the grader_submit tool that agents call when done grading.
Validates grading decisions and marks the grader run as complete.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AuthProvider
from fastmcp.tools import FunctionTool
from pydantic import BaseModel

from adgn.mcp._shared.types import MCPMountPrefix
from adgn.mcp.enhanced import EnhancedFastMCP
from adgn.openai_utils.pydantic_strict_mode import OpenAIStrictModeBaseModel
from adgn.props.db import get_session
from adgn.props.db.models import AgentRun, AgentRunStatus, GradingDecision, ReportedIssue

logger = logging.getLogger(__name__)

# Mount prefix constant for grader submit server
SUBMIT_PREFIX = MCPMountPrefix("grader_submit")


class GraderSubmitInput(OpenAIStrictModeBaseModel):
    """Input for grader_submit tool."""

    summary: str


class GraderSubmitResult(BaseModel):
    """Result of grader_submit."""

    message: str
    decisions_count: int
    input_issues_count: int


class ReportFailureInput(OpenAIStrictModeBaseModel):
    """Input for report_failure tool."""

    message: str


class GraderSubmitServer(EnhancedFastMCP):
    """MCP server for grader submit operations.

    Provides grader_submit and report_failure tools.
    """

    submit_tool: FunctionTool
    report_failure_tool: FunctionTool

    def __init__(self, *, grader_run_id: UUID, critic_run_id: UUID, auth: AuthProvider | None = None):
        """Initialize grader submit server.

        Args:
            grader_run_id: UUID of the grader run to finalize
            critic_run_id: UUID of the critic run being graded
            auth: Optional auth provider for HTTP mode
        """
        super().__init__("Grader Submit", instructions="Submit completed grading with validation", auth=auth)
        self._grader_run_id = grader_run_id
        self._critic_run_id = critic_run_id

        def submit(input: GraderSubmitInput) -> GraderSubmitResult:
            """Finalize grading and validate decisions.

            Call this when you're done grading all input issues. This will:
            1. Validate that every input issue has at least one decision
            2. Verify credit sums per occurrence don't exceed 1.0
            3. Mark the grader run as completed
            4. Store your summary

            Validations performed:
            - Every input issue must have at least one decision
            - Multiple decisions per input are allowed (e.g., input matches tp-A at 0.1 and tp-B at 0.2)
            - Credit sums validated (though SQL trigger already enforces ≤1.0)
            """
            try:
                return self._submit_grading(input.summary)
            except Exception as e:
                logger.exception("Grader submit failed: %s", e)
                raise ToolError(f"Failed to submit grading: {e}")

        self.submit_tool = self.flat_model()(submit)

        def report_failure(input: ReportFailureInput) -> None:
            """Report that grading could not be completed.

            Call this when you encounter blocking issues that prevent grading completion
            (e.g., malformed critic output, missing data, access issues).

            This marks the run as failed and stores the error message.
            """
            self._report_failure(input.message)

        self.report_failure_tool = self.flat_model()(report_failure)

    def _submit_grading(self, summary: str) -> GraderSubmitResult:
        """Submit grading with validation."""
        with get_session() as session:
            # Load grader run (now AgentRun)
            agent_run = session.get(AgentRun, self._grader_run_id)
            if agent_run is None:
                raise ToolError(f"Grader run {self._grader_run_id} not found")

            # Check if run is already in a terminal state
            if agent_run.status == AgentRunStatus.COMPLETED:
                raise ToolError(f"Grader run {self._grader_run_id} already completed")

            if agent_run.status == AgentRunStatus.REPORTED_FAILURE:
                raise ToolError(f"Grader run {self._grader_run_id} already reported failure")

            # Load reported issues from normalized table
            reported_issues = session.query(ReportedIssue).filter_by(agent_run_id=self._critic_run_id).all()

            # Extract input issue IDs from reported issues
            input_issue_ids = {issue.issue_id for issue in reported_issues}

            # Load all decisions for this grader run
            decisions = session.query(GradingDecision).filter_by(agent_run_id=self._grader_run_id).all()

            # Group decisions by input_issue_id
            decisions_by_input: dict[str, list[GradingDecision]] = {}
            for decision in decisions:
                if decision.input_issue_id not in decisions_by_input:
                    decisions_by_input[decision.input_issue_id] = []
                decisions_by_input[decision.input_issue_id].append(decision)

            # Validate: every input issue must have at least one decision
            # (Multiple decisions per input are allowed - e.g., "input-001 matches tp-A at 0.3 and tp-B at 0.5")
            missing_decisions = input_issue_ids - decisions_by_input.keys()
            if missing_decisions:
                raise ToolError(f"Missing grading decisions for input issues: {', '.join(sorted(missing_decisions))}")

            # Note: No need to check for "extra_decisions" (decisions for non-existent input issues).
            # Database CHECK constraint (validate_input_issue_exists) prevents those at INSERT time.

            # Mark run as completed and store summary
            agent_run.status = AgentRunStatus.COMPLETED
            agent_run.completion_summary = summary
            # Note: output field left as None - grading results are in grading_decisions table
            session.commit()

            logger.info(
                "Grader run %s completed: %d decisions for %d input issues",
                self._grader_run_id,
                len(decisions),
                len(input_issue_ids),
            )

            return GraderSubmitResult(
                message=f"Grading completed successfully with {len(decisions)} decisions",
                decisions_count=len(decisions),
                input_issues_count=len(input_issue_ids),
            )

    def _report_failure(self, message: str) -> None:
        """Report that grading could not be completed."""
        with get_session() as session:
            agent_run = session.get(AgentRun, self._grader_run_id)
            if agent_run is None:
                raise ToolError(f"Grader run {self._grader_run_id} not found")

            if agent_run.status == AgentRunStatus.COMPLETED:
                raise ToolError(f"Grader run {self._grader_run_id} already completed")

            if agent_run.status == AgentRunStatus.REPORTED_FAILURE:
                raise ToolError(f"Grader run {self._grader_run_id} already reported failure")

            agent_run.status = AgentRunStatus.REPORTED_FAILURE
            agent_run.completion_summary = message
            session.commit()

            logger.info("Grader run %s reported failure: %s", self._grader_run_id, message)
