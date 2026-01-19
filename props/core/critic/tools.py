"""Critic agent tool argument and result models."""

from __future__ import annotations

from pydantic import BaseModel, Field


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


# --- Result models ---


class IssueInfo(BaseModel):
    """Issue information for list_issues output."""

    issue_id: str
    rationale: str
    occurrence_count: int
