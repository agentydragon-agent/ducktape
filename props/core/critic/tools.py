"""Critic agent tools for the in-container agent loop.

These tools are called directly by the agent loop, not via CLI subprocess.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from props.core.agent_helpers import get_current_agent_run_id
from props.core.db.models import AgentRun, AgentRunStatus, ReportedIssue, ReportedIssueOccurrence
from props.core.db.session import get_session
from props.core.db.snapshots import DBLocationAnchor

logger = logging.getLogger(__name__)


# --- Tool argument models ---


class InsertIssueArgs(BaseModel):
    """Arguments for insert_issue tool."""

    issue_id: str = Field(..., description="Unique identifier for this issue (kebab-case slug)")
    rationale: str = Field(..., description="Explanation of why this is an issue")


class InsertOccurrenceArgs(BaseModel):
    """Arguments for insert_occurrence tool."""

    issue_id: str = Field(..., description="ID of the issue this occurrence belongs to")
    file: str = Field(..., description="File path relative to workspace root")
    start_line: int | None = Field(None, description="Starting line number")
    end_line: int | None = Field(None, description="Ending line number")


class LocationSpec(BaseModel):
    """A single location in insert_occurrence_multi."""

    file: str
    start_line: int | None = None
    end_line: int | None = None


class InsertOccurrenceMultiArgs(BaseModel):
    """Arguments for insert_occurrence_multi tool."""

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
    exit_code: int = 0


# --- Tool implementations ---


def insert_issue(args: InsertIssueArgs) -> ToolResult:
    """Insert a reported issue."""
    with get_session() as session:
        agent_run_id = get_current_agent_run_id(session)
        issue = ReportedIssue(agent_run_id=agent_run_id, issue_id=args.issue_id, rationale=args.rationale)
        session.add(issue)
    return ToolResult(output=f"Inserted issue: {args.issue_id}")


def insert_occurrence(args: InsertOccurrenceArgs) -> ToolResult:
    """Insert a single-location occurrence for a reported issue."""
    with get_session() as session:
        agent_run_id = get_current_agent_run_id(session)
        occurrence = ReportedIssueOccurrence(
            agent_run_id=agent_run_id,
            reported_issue_id=args.issue_id,
            locations=[DBLocationAnchor(file=args.file, start_line=args.start_line, end_line=args.end_line)],
        )
        session.add(occurrence)

    location = args.file
    if args.start_line is not None:
        location += f":{args.start_line}"
        if args.end_line is not None and args.end_line != args.start_line:
            location += f"-{args.end_line}"
    return ToolResult(output=f"Inserted occurrence for {args.issue_id}: {location}")


def insert_occurrence_multi(args: InsertOccurrenceMultiArgs) -> ToolResult:
    """Insert a multi-location occurrence (e.g., duplication across files)."""
    with get_session() as session:
        agent_run_id = get_current_agent_run_id(session)
        occurrence = ReportedIssueOccurrence(
            agent_run_id=agent_run_id,
            reported_issue_id=args.issue_id,
            locations=[DBLocationAnchor(file=loc.file, start_line=loc.start_line, end_line=loc.end_line) for loc in args.locations],
        )
        session.add(occurrence)
    return ToolResult(output=f"Inserted multi-location occurrence for {args.issue_id}: {len(args.locations)} locations")


def delete_issue(args: DeleteIssueArgs) -> ToolResult:
    """Delete a reported issue and all its occurrences."""
    with get_session() as session:
        issue = session.query(ReportedIssue).filter_by(issue_id=args.issue_id).first()
        if issue is None:
            return ToolResult(output=f"Error: Issue not found: {args.issue_id}")
        session.delete(issue)
    return ToolResult(output=f"Deleted issue: {args.issue_id}")


def list_issues() -> ToolResult:
    """List all issues reported in this critique run."""
    with get_session() as session:
        agent_run_id = get_current_agent_run_id(session)
        issues = session.query(ReportedIssue).filter_by(agent_run_id=agent_run_id).all()

        if not issues:
            return ToolResult(output="No issues reported yet.")

        lines = [f"Issues reported ({len(issues)}):"]
        for issue in issues:
            occurrences = (
                session.query(ReportedIssueOccurrence)
                .filter_by(agent_run_id=agent_run_id, reported_issue_id=issue.issue_id)
                .all()
            )
            lines.append(f"  {issue.issue_id}")
            lines.append(f"    Rationale: {issue.rationale}")
            lines.append(f"    Occurrences: {len(occurrences)}")
            for occ in occurrences:
                locs = ", ".join(f"{loc.file}:{loc.start_line or '?'}-{loc.end_line or '?'}" for loc in occ.locations)
                lines.append(f"      - {locs}")

        return ToolResult(output="\n".join(lines))


def _validate_occurrence(occ: ReportedIssueOccurrence) -> str | None:
    """Validate a single occurrence. Returns error message or None if valid."""
    if not occ.locations or len(occ.locations) == 0:
        return f"Occurrence {occ.id} must have at least one location"

    for i, loc in enumerate(occ.locations):
        if not isinstance(loc, DBLocationAnchor):
            return f"Location {i} must be a DBLocationAnchor, got {type(loc)}"

        if loc.start_line is not None:
            if loc.start_line <= 0:
                return f"Location {i}: start_line must be > 0, got {loc.start_line}"

            if loc.end_line is not None and loc.end_line < loc.start_line:
                return f"Location {i}: end_line ({loc.end_line}) must be >= start_line ({loc.start_line})"

    return None


def submit(args: SubmitArgs) -> ToolResult:
    """Finalize the critique and validate reported issues.

    Returns should_exit=True with exit_code=0 on success.
    Returns error message on validation failure.
    """
    with get_session() as session:
        agent_run_id = get_current_agent_run_id(session)
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
            occurrences = (
                session.query(ReportedIssueOccurrence)
                .filter_by(agent_run_id=agent_run_id, reported_issue_id=issue.issue_id)
                .all()
            )

            if len(occurrences) == 0:
                return ToolResult(
                    output=f"Error: Issue '{issue.issue_id}' has no occurrences. "
                    f"Every issue must have at least one occurrence showing where it occurs in the code."
                )

            total_occurrences += len(occurrences)

            for occ in occurrences:
                error = _validate_occurrence(occ)
                if error:
                    return ToolResult(output=f"Error: {error}")

        agent_run.status = AgentRunStatus.COMPLETED
        agent_run.completion_summary = args.summary

    logger.info("Critique submitted: %d issues, %d occurrences", args.issues_count, total_occurrences)
    return ToolResult(
        output=f"Submitted critique: {args.issues_count} issues, {total_occurrences} occurrences",
        should_exit=True,
        exit_code=0,
    )


def report_failure(args: ReportFailureArgs) -> ToolResult:
    """Report that critique could not be completed."""
    with get_session() as session:
        agent_run_id = get_current_agent_run_id(session)
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
    return ToolResult(output=f"Reported failure: {args.message}", should_exit=True, exit_code=1)


# --- Tool schemas for OpenAI ---


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
            "Insert a single-location occurrence for a reported issue. The issue must exist first.",
            InsertOccurrenceArgs,
        ),
        make_schema(
            "insert_occurrence_multi",
            "Insert a multi-location occurrence (e.g., duplication across files). Use for issues spanning multiple locations.",
            InsertOccurrenceMultiArgs,
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
                "description": "List all issues reported in this critique run. Shows issue IDs, rationales, and occurrence counts.",
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
