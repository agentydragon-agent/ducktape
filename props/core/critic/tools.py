"""Critic agent tools for the in-container agent loop.

These tools are called directly by the agent loop, not via CLI subprocess.
"""

from __future__ import annotations

import logging
from uuid import UUID

from pydantic import BaseModel, Field

from props.core.db.models import AgentRun, AgentRunStatus, ReportedIssue, ReportedIssueOccurrence
from props.core.db.session import get_session

logger = logging.getLogger(__name__)


# --- Tool argument models ---


class InsertIssueArgs(BaseModel):
    """Arguments for insert_issue tool."""

    issue_id: str = Field(..., description="Unique identifier for this issue (kebab-case slug)")
    rationale: str = Field(..., description="Explanation of why this is an issue")


class LocationSpec(BaseModel):
    """A single location for an occurrence."""

    file: str = Field(..., description="File path relative to workspace root")
    start_line: int | None = Field(None, description="Starting line number")
    end_line: int | None = Field(None, description="Ending line number")


class InsertOccurrenceArgs(BaseModel):
    """Arguments for insert_occurrence tool."""

    issue_id: str = Field(..., description="ID of the issue this occurrence belongs to")
    locations: list[LocationSpec] = Field(..., description="List of locations for this occurrence")


class DeleteIssueArgs(BaseModel):
    """Arguments for delete_issue tool."""

    issue_id: str = Field(..., description="ID of the issue to delete")


class SubmitArgs(BaseModel):
    """Arguments for submit tool."""

    issues_count: int = Field(..., description="Total number of issues reported")
    summary: str = Field(..., description="Brief summary of the code review findings")


class ReportFailureArgs(BaseModel):
    """Arguments for report_failure tool."""

    message: str = Field(..., description="Description of why the critique could not be completed")


# --- Tool result models ---


class SubmitResult(BaseModel):
    """Result from successful submit."""

    issues_count: int
    occurrences_count: int
    message: str


# --- Tool implementations ---


def _get_in_progress_run(session: object, agent_run_id: UUID) -> AgentRun:
    """Get agent run, ensuring it exists and is in progress.

    Args:
        session: Database session (typed as object to avoid sqlalchemy import complexity)
        agent_run_id: ID of the agent run

    Raises:
        RuntimeError: If agent run not found or not in progress
    """
    agent_run = session.get(AgentRun, agent_run_id)  # type: ignore[union-attr]
    if agent_run is None:
        raise RuntimeError(f"Agent run {agent_run_id} not found")
    if agent_run.status != AgentRunStatus.IN_PROGRESS:
        raise RuntimeError(f"Agent run {agent_run_id} not in progress (status: {agent_run.status})")
    return agent_run


class IssueInfo(BaseModel):
    """Issue information for list_issues output."""

    issue_id: str
    rationale: str
    occurrence_count: int


class ListIssuesOutput(BaseModel):
    """Output from list_issues tool."""

    issues: list[IssueInfo]


def list_issues(agent_run_id: UUID) -> ListIssuesOutput:
    """List all issues reported in this critique run."""
    with get_session() as session:
        issues = session.query(ReportedIssue).filter_by(agent_run_id=agent_run_id).all()

        issue_infos = []
        for issue in issues:
            occurrence_count = (
                session.query(ReportedIssueOccurrence)
                .filter_by(agent_run_id=agent_run_id, reported_issue_id=issue.issue_id)
                .count()
            )
            issue_infos.append(IssueInfo(issue_id=issue.issue_id, rationale=issue.rationale, occurrence_count=occurrence_count))

        return ListIssuesOutput(issues=issue_infos)


def submit(agent_run_id: UUID, args: SubmitArgs) -> SubmitResult:
    """Finalize the critique and validate reported issues.

    Raises:
        ValueError: If validation fails (count mismatch, missing occurrences, etc.)
        RuntimeError: If agent run not found or not in progress
    """
    with get_session() as session:
        agent_run = _get_in_progress_run(session, agent_run_id)

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

        agent_run.status = AgentRunStatus.COMPLETED
        agent_run.completion_summary = args.summary

    logger.info("Critique submitted: %d issues, %d occurrences", args.issues_count, total_occurrences)
    return SubmitResult(
        issues_count=args.issues_count,
        occurrences_count=total_occurrences,
        message=f"Submitted critique: {args.issues_count} issues, {total_occurrences} occurrences",
    )


def report_failure(agent_run_id: UUID, args: ReportFailureArgs) -> str:
    """Report that critique could not be completed.

    Raises:
        RuntimeError: If agent run not found or not in progress
    """
    with get_session() as session:
        agent_run = _get_in_progress_run(session, agent_run_id)
        agent_run.status = AgentRunStatus.REPORTED_FAILURE
        agent_run.completion_summary = args.message

    logger.info("Reported failure: %s", args.message)
    return f"Reported failure: {args.message}"
