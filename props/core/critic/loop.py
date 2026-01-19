"""In-container agent loop for critic agents using agent_core.Agent.

Runs the full agent loop inside the container:
1. Fetches agent_run_id from environment
2. Constructs system prompt
3. Calls LLM via proxy (OPENAI_BASE_URL)
4. Executes tools (both shell exec and critic-specific tools)
5. Exits on successful submit or reported failure
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from openai import AsyncOpenAI

from agent_core.agent import Agent
from agent_core.direct_provider import DirectToolProvider
from agent_core.handler import AbortIf, BaseHandler, RedirectOnTextMessageHandler
from agent_core.loop_control import AllowAnyToolOrTextMessage
from mcp_infra.exec.models import BaseExecResult
from mcp_infra.exec.subprocess_exec import SubprocessExecArgs, run_exec
from openai_utils.model import BoundOpenAIModel, SystemMessage
from props.core.agent_helpers import get_current_agent_run_id
from props.core.critic.tools import (
    DeleteIssueArgs,
    InsertIssueArgs,
    InsertOccurrenceArgs,
    IssueInfo,
    ReportFailureArgs,
    SubmitArgs,
)
from props.core.db.models import ReportedIssue, ReportedIssueOccurrence
from props.core.db.session import get_session
from props.core.db.snapshots import DBLocationAnchor

logger = logging.getLogger(__name__)

# Reminder sent when agent outputs text instead of using tools
TEXT_OUTPUT_REMINDER = (
    "You must use tools to report issues. Do not output text directly. "
    "Use insert_issue and insert_occurrence to report issues, then call submit when done."
)

# Default workspace path
WORKSPACE = Path("/workspace")


@dataclass
class ExitState:
    """Tracks whether a tool has requested exit."""

    should_exit: bool = False


def create_critic_tool_provider(agent_run_id: UUID, exit_state: ExitState) -> DirectToolProvider:
    """Create a tool provider with critic tools bound to the given agent run."""
    provider = DirectToolProvider()

    @provider.tool
    async def exec(args: SubprocessExecArgs) -> BaseExecResult:
        """Execute a shell command. Use for file operations, running tests, etc."""
        return await run_exec(args, default_cwd=WORKSPACE)

    @provider.tool
    def insert_issue(args: InsertIssueArgs) -> str:
        """Insert a reported issue. Call this before adding occurrences for the issue."""
        with get_session() as session:
            issue = ReportedIssue(agent_run_id=agent_run_id, issue_id=args.issue_id, rationale=args.rationale)
            session.add(issue)
        return f"Inserted issue: {args.issue_id}"

    @provider.tool
    def insert_occurrence(args: InsertOccurrenceArgs) -> str:
        """Insert an occurrence for a reported issue. The issue must exist first.

        An occurrence can span multiple locations (e.g., duplicated code across files).
        """
        with get_session() as session:
            occurrence = ReportedIssueOccurrence(
                agent_run_id=agent_run_id,
                reported_issue_id=args.issue_id,
                locations=[
                    DBLocationAnchor(file=loc.file, start_line=loc.start_line, end_line=loc.end_line)
                    for loc in args.locations
                ],
            )
            session.add(occurrence)
        return f"Inserted occurrence for {args.issue_id}"

    @provider.tool
    def delete_issue(args: DeleteIssueArgs) -> str:
        """Delete a reported issue and all its occurrences. Use to remove incorrect issues."""
        with get_session() as session:
            issue = session.query(ReportedIssue).filter_by(issue_id=args.issue_id).first()
            if issue is None:
                raise ValueError(f"Issue not found: {args.issue_id}")
            session.delete(issue)
        return f"Deleted issue: {args.issue_id}"

    @provider.tool
    def list_issues() -> list[IssueInfo]:
        """List all issues reported in this critique run.

        Returns issue IDs, rationales, and occurrence counts.
        """
        with get_session() as session:
            issues = session.query(ReportedIssue).filter_by(agent_run_id=agent_run_id).all()
            return [
                IssueInfo(
                    issue_id=issue.issue_id,
                    rationale=issue.rationale,
                    occurrence_count=session.query(ReportedIssueOccurrence)
                    .filter_by(agent_run_id=agent_run_id, reported_issue_id=issue.issue_id)
                    .count(),
                )
                for issue in issues
            ]

    @provider.tool
    def submit(args: SubmitArgs) -> None:
        """Finalize and submit the critique.

        Validates all issues then signals exit. Host updates agent_run status based on exit code.
        """
        with get_session() as session:
            issues = session.query(ReportedIssue).filter_by(agent_run_id=agent_run_id).all()

            actual_issues_count = len(issues)
            if args.issues_count != actual_issues_count:
                raise ValueError(
                    f"Issues count mismatch: expected {args.issues_count} but found {actual_issues_count} in database"
                )

            total_occurrences = 0
            for issue in issues:
                occurrence_count = (
                    session.query(ReportedIssueOccurrence)
                    .filter_by(agent_run_id=agent_run_id, reported_issue_id=issue.issue_id)
                    .count()
                )
                if occurrence_count == 0:
                    raise ValueError(
                        f"Issue '{issue.issue_id}' has no occurrences. "
                        f"Every issue must have at least one occurrence showing where it occurs in the code."
                    )
                total_occurrences += occurrence_count

        exit_state.should_exit = True
        logger.info("Critique submitted: %d issues, %d occurrences", args.issues_count, total_occurrences)

    @provider.tool
    def report_failure(args: ReportFailureArgs) -> None:
        """Report that the critique could not be completed.

        Use when there are blocking issues (e.g., no files in scope).
        Signals exit; host updates agent_run status based on exit code.
        """
        exit_state.should_exit = True
        logger.info("Reported failure: %s", args.message)

    return provider


class LoggingHandler(BaseHandler):
    """Handler that logs events for debugging."""

    def on_error(self, exc: Exception) -> None:
        logger.error("Agent error: %s", exc)
        raise exc


async def run_critic_loop(system_prompt: str, model: str) -> int:
    """Run the critic agent loop.

    Args:
        system_prompt: The system prompt for the critic agent
        model: Model name (must match agent_run.model for proxy validation)

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    # Get agent_run_id once at the start
    with get_session() as session:
        agent_run_id = get_current_agent_run_id(session)

    # Create tool provider with shared exit state
    exit_state = ExitState()
    tool_provider = create_critic_tool_provider(agent_run_id, exit_state)

    # Create OpenAI client pointing to proxy
    client = AsyncOpenAI(
        base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        api_key=os.environ.get("OPENAI_API_KEY", ""),
    )
    bound_model = BoundOpenAIModel(client=client, model=model)

    # Create handlers
    handlers: list[BaseHandler] = [
        LoggingHandler(),
        RedirectOnTextMessageHandler(TEXT_OUTPUT_REMINDER),
        AbortIf(lambda: exit_state.should_exit),
    ]

    # Create and run agent
    agent = await Agent.create(
        tool_provider=tool_provider,
        handlers=handlers,
        client=bound_model,
        parallel_tool_calls=False,  # Execute tools sequentially for clarity
        tool_policy=AllowAnyToolOrTextMessage(),
    )

    # Add system prompt
    agent.process_message(SystemMessage.text(system_prompt))

    await agent.run()
    if exit_state.should_exit:
        print("Critique completed")
        return 0
    # Agent finished without explicit exit (shouldn't happen with proper abort handling)
    logger.warning("Agent finished without explicit exit")
    return 1
