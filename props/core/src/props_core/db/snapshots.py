"""Database-specific models for canonical issue snapshots.

These models are the persistence layer for issue data and are intentionally
decoupled from MCP I/O models (grader.models.*) to avoid coupling database
migrations to protocol changes.

Key differences from MCP models:
- All Path objects stored as strings
- All sets stored as lists (simpler JSON representation)
- No complex types like NewType wrappers
- No Pydantic validators (data already validated before storage)
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DBLineRange(BaseModel):
    """Database representation of a line range."""

    start_line: int = Field(ge=1)
    end_line: int | None = Field(default=None)

    model_config = ConfigDict(extra="forbid", frozen=True)


class DBLocationAnchor(BaseModel):
    """Database representation of a location anchor for reported issues.

    Matches the YAML ground truth format:
    - file: required file path
    - start_line: optional line number (1-based)
    - end_line: optional end line (inclusive)
    """

    file: str = Field(description="File path (relative to snapshot root)")
    start_line: int | None = Field(default=None, ge=1, description="Optional start line (1-based)")
    end_line: int | None = Field(default=None, ge=1, description="Optional end line (inclusive)")

    model_config = ConfigDict(extra="forbid", frozen=True)


class DBTruePositiveOccurrence(BaseModel):
    """Database representation of a true positive occurrence."""

    occurrence_id: str = Field(description="Unique ID within this TP")
    files: dict[str, list[DBLineRange] | None] = Field(description="File paths (as strings) mapped to line ranges")
    note: str | None = Field(default=None)
    critic_scopes_expected_to_recall: list[list[str]] = Field(
        description="Critic scope file sets where this counts toward recall (list of alternatives)"
    )

    model_config = ConfigDict(extra="forbid", frozen=True)


class DBFalsePositiveOccurrence(BaseModel):
    """Database representation of a false positive occurrence."""

    occurrence_id: str = Field(description="Unique ID within this FP")
    files: dict[str, list[DBLineRange] | None] = Field(description="File paths (as strings) mapped to line ranges")
    note: str | None = Field(default=None)
    relevant_files: list[str] = Field(description="Files that make this FP relevant")

    model_config = ConfigDict(extra="forbid", frozen=True)


class DBTruePositiveIssue(BaseModel):
    """Database representation of a true positive issue.

    This is the persisted form, decoupled from MCP I/O types.
    """

    id: str = Field(description="Issue ID (stored as string)")
    rationale: str = Field(description="Issue rationale (stored as string)")
    occurrences: list[DBTruePositiveOccurrence]

    model_config = ConfigDict(extra="forbid", frozen=True)


class DBKnownFalsePositive(BaseModel):
    """Database representation of a known false positive.

    This is the persisted form, decoupled from MCP I/O types.
    """

    id: str = Field(description="False positive ID (stored as string)")
    rationale: str = Field(description="FP rationale (stored as string)")
    occurrences: list[DBFalsePositiveOccurrence]

    model_config = ConfigDict(extra="forbid", frozen=True)


# =============================================================================
# Critic Submit Payload Models (DB persistence for critique payloads)
# =============================================================================


class DBFileOccurrence(BaseModel):
    """Database representation of one file in an occurrence."""

    path: str = Field(description="File path (stored as string)")
    ranges: list[DBLineRange] | None = Field(default=None, description="Line ranges or None for unspecified")

    model_config = ConfigDict(extra="forbid", frozen=True)


class DBOccurrence(BaseModel):
    """Database representation of an occurrence (critic-reported issue).

    Simpler than TruePositiveOccurrence - no critic_scopes_expected_to_recall tracking.
    """

    files: list[DBFileOccurrence] = Field(description="Files with line ranges")
    note: str | None = Field(default=None, description="Occurrence-specific note")

    model_config = ConfigDict(extra="forbid", frozen=True)


class DBReportedIssue(BaseModel):
    """Database representation of a reported issue from critic."""

    id: str = Field(description="Issue ID (stored as string)")
    rationale: str = Field(description="Issue rationale (stored as string)")
    occurrences: list[DBOccurrence] = Field(description="Issue occurrences")

    model_config = ConfigDict(extra="forbid", frozen=True)


class DBCriticSubmitPayload(BaseModel):
    """Database representation of critic submit payload.

    Issues are stored in normalized reported_issues table, not here.
    Access via critic_run.reported_issues ORM relationship.
    """

    notes_md: str | None = Field(default=None, description="Optional Markdown notes")

    model_config = ConfigDict(extra="forbid", frozen=True)


# =============================================================================
# Grading Result Models (for test fixtures)
# =============================================================================


class DBOccurrenceMatch(BaseModel):
    """Database representation of match between input issue and canonical occurrence."""

    input_id: str = Field(description="Input issue ID (stored as string)")
    credit: float = Field(ge=0.0, le=1.0, description="Credit for this match")

    model_config = ConfigDict(extra="forbid", frozen=True)


class DBOccurrenceResult(BaseModel):
    """Database representation of grading result for a single occurrence."""

    tp_id: str = Field(description="True positive ID (stored as string)")
    occurrence_id: str = Field(description="Occurrence identifier")
    found_credit: float = Field(ge=0.0, le=1.0, description="Overall credit for finding this occurrence")
    matched_by: list[DBOccurrenceMatch] = Field(description="Which input issues matched and their credits")
    rationale: str = Field(description="Rationale (stored as string)")

    model_config = ConfigDict(extra="forbid", frozen=True)


class DBUnknownIssue(BaseModel):
    """Database representation of an input issue with novel aspects not matched to any canonical issue."""

    id: str = Field(description="Unknown issue ID (stored as string)")
    rationale: str = Field(description="Why this issue is novel/unknown (stored as string)")

    model_config = ConfigDict(extra="forbid", frozen=True)
