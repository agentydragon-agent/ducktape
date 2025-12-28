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
from props_core.db.models import AgentRun, AgentRunStatus, GradingDecision, ReportedIssue
from props_core.db.session import get_session

from mcp_infra.enhanced import EnhancedFastMCP
from mcp_infra.prefix import MCPMountPrefix
from openai_utils.pydantic_strict_mode import OpenAIStrictModeBaseModel

logger = logging.getLogger(__name__)

# Mount prefix constant for grader submit server
SUBMIT_PREFIX = MCPMountPrefix("grader_submit")


class GraderSubmitInput(OpenAIStrictModeBaseModel):
    """Input for grader_submit tool."""

    summary: str


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

        def submit(input: GraderSubmitInput) -> None:
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
            with get_session() as session:
                agent_run = session.get(AgentRun, self._grader_run_id)
                if agent_run is None:
                    raise ToolError(f"Grader run {self._grader_run_id} not found")

                if agent_run.status == AgentRunStatus.COMPLETED:
                    raise ToolError(f"Grader run {self._grader_run_id} already completed")

                if agent_run.status == AgentRunStatus.REPORTED_FAILURE:
                    raise ToolError(f"Grader run {self._grader_run_id} already reported failure")

                input_issue_ids = {
                    i.issue_id for i in session.query(ReportedIssue).filter_by(agent_run_id=self._critic_run_id)
                }
                decided_ids = {
                    d.input_issue_id for d in session.query(GradingDecision).filter_by(agent_run_id=self._grader_run_id)
                }
                missing = input_issue_ids - decided_ids
                if missing:
                    raise ToolError(f"Missing grading decisions for: {', '.join(sorted(missing))}")

                agent_run.status = AgentRunStatus.COMPLETED
                agent_run.completion_summary = input.summary
                session.commit()
                logger.info("Grader run %s completed", self._grader_run_id)

        self.submit_tool = self.flat_model()(submit)

        def report_failure(input: ReportFailureInput) -> None:
            """Report that grading could not be completed.

            Call this when you encounter blocking issues that prevent grading completion
            (e.g., malformed critic output, missing data, access issues).

            This marks the run as failed and stores the error message.
            """
            with get_session() as session:
                agent_run = session.get(AgentRun, self._grader_run_id)
                if agent_run is None:
                    raise ToolError(f"Grader run {self._grader_run_id} not found")

                if agent_run.status == AgentRunStatus.COMPLETED:
                    raise ToolError(f"Grader run {self._grader_run_id} already completed")

                if agent_run.status == AgentRunStatus.REPORTED_FAILURE:
                    raise ToolError(f"Grader run {self._grader_run_id} already reported failure")

                agent_run.status = AgentRunStatus.REPORTED_FAILURE
                agent_run.completion_summary = input.message
                session.commit()

                logger.info("Grader run %s reported failure: %s", self._grader_run_id, input.message)

        self.report_failure_tool = self.flat_model()(report_failure)
