"""Critic agent tools for the in-container agent loop.

These tools are called directly by the agent loop, not via CLI subprocess.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from props.core.db.models import AgentRun, AgentRunStatus, ReportedIssue, ReportedIssueOccurrence
from props.core.db.session import get_session
from props.core.db.snapshots import DBLocationAnchor

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


# --- Tool result ---


@dataclass
class ToolResult:
    """Result from a critic tool invocation."""

    output: str
    should_exit: bool = False


# --- Tool implementations ---


def insert_issue(agent_run_id: UUID, args: InsertIssueArgs) -> ToolResult:
    """Insert a reported issue."""
    with get_session() as session:
        issue = ReportedIssue(agent_run_id=agent_run_id, issue_id=args.issue_id, rationale=args.rationale)
        session.add(issue)
    return ToolResult(output=f"Inserted issue: {args.issue_id}")


def insert_occurrence(agent_run_id: UUID, args: InsertOccurrenceArgs) -> ToolResult:
    """Insert an occurrence (one or more locations) for a reported issue."""
    with get_session() as session:
        occurrence = ReportedIssueOccurrence(
            agent_run_id=agent_run_id,
            reported_issue_id=args.issue_id,
            locations=[DBLocationAnchor(file=loc.file, start_line=loc.start_line, end_line=loc.end_line) for loc in args.locations],
        )
        session.add(occurrence)
    return ToolResult(output=f"Inserted occurrence for {args.issue_id}")


def delete_issue(args: DeleteIssueArgs) -> ToolResult:
    """Delete a reported issue and all its occurrences."""
    with get_session() as session:
        issue = session.query(ReportedIssue).filter_by(issue_id=args.issue_id).first()
        if issue is None:
            return ToolResult(output=f"Error: Issue not found: {args.issue_id}")
        session.delete(issue)
    return ToolResult(output=f"Deleted issue: {args.issue_id}")


class IssueInfo(BaseModel):
    """Issue information for list_issues output."""

    issue_id: str
    rationale: str
    occurrence_count: int


class ListIssuesOutput(BaseModel):
    """Output from list_issues tool."""

    issues: list[IssueInfo]


def list_issues(agent_run_id: UUID) -> ToolResult:
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

        output = ListIssuesOutput(issues=issue_infos)
        return ToolResult(output=json.dumps(output.model_dump(), indent=2))


def submit(agent_run_id: UUID, args: SubmitArgs) -> ToolResult:
    """Finalize the critique and validate reported issues."""
    with get_session() as session:
        agent_run = session.get(AgentRun, agent_run_id)

        if agent_run is None:
            return ToolResult(output=f"Error: Agent run {agent_run_id} not found")

        if agent_run.status == AgentRunStatus.COMPLETED:
            return ToolResult(output=f"Error: Agent run {agent_run_id} already completed")

        issues = session.query(ReportedIssue).filter_by(agent_run_id=agent_run_id).all()

        actual_issues_count = len(issues)
        if args.issues_count != actual_issues_count:
            return ToolResult(
                output=f"Error: Issues count mismatch: expected {args.issues_count} but found {actual_issues_count} in database"
            )

        total_occurrences = 0
        for issue in issues:
            occurrence_count = (
                session.query(ReportedIssueOccurrence)
                .filter_by(agent_run_id=agent_run_id, reported_issue_id=issue.issue_id)
                .count()
            )

            if occurrence_count == 0:
                return ToolResult(
                    output=f"Error: Issue '{issue.issue_id}' has no occurrences. "
                    f"Every issue must have at least one occurrence showing where it occurs in the code."
                )

            total_occurrences += occurrence_count

        agent_run.status = AgentRunStatus.COMPLETED
        agent_run.completion_summary = args.summary

    logger.info("Critique submitted: %d issues, %d occurrences", args.issues_count, total_occurrences)
    return ToolResult(
        output=f"Submitted critique: {args.issues_count} issues, {total_occurrences} occurrences",
        should_exit=True,
    )


def report_failure(agent_run_id: UUID, args: ReportFailureArgs) -> ToolResult:
    """Report that critique could not be completed."""
    with get_session() as session:
        agent_run = session.get(AgentRun, agent_run_id)

        if agent_run is None:
            return ToolResult(output=f"Error: Agent run {agent_run_id} not found")

        if agent_run.status == AgentRunStatus.COMPLETED:
            return ToolResult(output=f"Error: Agent run {agent_run_id} already completed")

        if agent_run.status == AgentRunStatus.REPORTED_FAILURE:
            return ToolResult(output=f"Error: Agent run {agent_run_id} already reported failure")

        agent_run.status = AgentRunStatus.REPORTED_FAILURE
        agent_run.completion_summary = args.message

    logger.info("Reported failure: %s", args.message)
    return ToolResult(output=f"Reported failure: {args.message}", should_exit=True)


# --- Tool schemas for OpenAI ---

CRITIC_TOOL_NAMES = frozenset({"insert_issue", "insert_occurrence", "delete_issue", "list_issues", "submit", "report_failure"})


def get_critic_tool_schemas() -> list[dict[str, Any]]:
    """Return tool schemas for all critic tools."""

    def make_schema(name: str, description: str, model: type[BaseModel]) -> dict[str, Any]:
        parameters = model.model_json_schema()
        parameters.pop("$defs", None)
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
                "strict": True,
            },
        }

    return [
        make_schema(
            "insert_issue",
            "Insert a reported issue. Call this before adding occurrences for the issue.",
            InsertIssueArgs,
        ),
        make_schema(
            "insert_occurrence",
            "Insert an occurrence for a reported issue. The issue must exist first. "
            "An occurrence can span multiple locations (e.g., duplicated code across files).",
            InsertOccurrenceArgs,
        ),
        make_schema(
            "delete_issue",
            "Delete a reported issue and all its occurrences. Use to remove incorrect issues.",
            DeleteIssueArgs,
        ),
        {
            "type": "function",
            "function": {
                "name": "list_issues",
                "description": "List all issues reported in this critique run. Returns JSON with issue IDs, rationales, and occurrence counts.",
                "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
                "strict": True,
            },
        },
        make_schema(
            "submit",
            "Finalize and submit the critique. Validates all issues and marks the run as complete. Call this when done reviewing.",
            SubmitArgs,
        ),
        make_schema(
            "report_failure",
            "Report that the critique could not be completed due to blocking issues (e.g., no files in scope).",
            ReportFailureArgs,
        ),
    ]
