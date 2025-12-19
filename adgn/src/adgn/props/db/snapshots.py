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

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class DBLineRange(BaseModel):
    """Database representation of a line range."""

    start_line: int = Field(ge=1)
    end_line: int | None = Field(default=None)

    model_config = ConfigDict(extra="forbid", frozen=True)


class DBLocationAnchor(BaseModel):
    """Database representation of a location anchor for reported issues.

    Matches the libsonnet ground truth format:
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
    expect_caught_from: list[list[str]] = Field(
        description="Minimal file sets for detection (list of alternatives, each alternative is list of paths)"
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

    Simpler than TruePositiveOccurrence - no expect_caught_from tracking.
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
# Critic Output Models (Discriminated Union)
# =============================================================================


class DBCriticSuccess(BaseModel):
    """Database representation of successful critic output."""

    tag: Literal["success"] = "success"
    result: DBCriticSubmitPayload = Field(description="Successful critique with issues and optional notes")

    model_config = ConfigDict(extra="forbid", frozen=True)


class DBCriticMaxTurnsExceeded(BaseModel):
    """Database representation of critic running out of turns."""

    tag: Literal["max_turns_exceeded"] = "max_turns_exceeded"
    max_turns: int = Field(description="Maximum turns that were allowed", gt=0)

    model_config = ConfigDict(extra="forbid", frozen=True)


class DBCriticContextLengthExceeded(BaseModel):
    """Database representation of critic input exceeding context window."""

    tag: Literal["context_length_exceeded"] = "context_length_exceeded"
    error_message: str = Field(description="Error message from the API")

    model_config = ConfigDict(extra="forbid", frozen=True)


class DBCriticReportedFailure(BaseModel):
    """Database representation of critic explicitly reporting it cannot complete."""

    tag: Literal["reported_failure"] = "reported_failure"
    reason: str = Field(description="Reason provided by the critic for inability to complete")

    model_config = ConfigDict(extra="forbid", frozen=True)


DBCriticOutput = Annotated[
    DBCriticSuccess | DBCriticMaxTurnsExceeded | DBCriticContextLengthExceeded | DBCriticReportedFailure,
    Field(
        discriminator="tag",
        description="Critic output: success, max turns exceeded, context length exceeded, or reported failure",
    ),
]
"""Discriminated union of critic outcomes for database persistence."""


class DBIssueCoverageEntry(BaseModel):
    """Database representation of single input issue's contribution to canonical coverage."""

    input_id: str = Field(description="Input issue ID (stored as string)")
    credit: float = Field(ge=0.0, le=1.0, description="Individual recall credit contribution")

    model_config = ConfigDict(extra="forbid", frozen=True)


class DBCanonicalTPCoverage(BaseModel):
    """Database representation of coverage of a canonical TP."""

    covered_by: list[DBIssueCoverageEntry] = Field(description="Input issue contributions")
    recall_credit: float = Field(ge=0.0, le=1.0, description="Total recall credit")
    rationale: str = Field(description="Rationale (stored as string)")

    model_config = ConfigDict(extra="forbid", frozen=True)


class DBTPCoverageEntry(BaseModel):
    """Database representation of coverage for one canonical true positive."""

    canonical_id: str = Field(description="Canonical TP ID (stored as string)")
    coverage: DBCanonicalTPCoverage

    model_config = ConfigDict(extra="forbid", frozen=True)


class DBCanonicalFPCoverage(BaseModel):
    """Database representation of coverage of a known FP."""

    covered_by: list[str] = Field(description="Input issue IDs that matched this known FP (stored as strings)")
    rationale: str = Field(description="Rationale (stored as string)")

    model_config = ConfigDict(extra="forbid", frozen=True)


class DBFPCoverageEntry(BaseModel):
    """Database representation of coverage for one known false positive."""

    canonical_id: str = Field(description="Known FP ID (stored as string)")
    coverage: DBCanonicalFPCoverage

    model_config = ConfigDict(extra="forbid", frozen=True)


class DBNovelIssueReasoning(BaseModel):
    """Database representation of rationale for novel aspects."""

    rationale: str = Field(description="Rationale (stored as string)")

    model_config = ConfigDict(extra="forbid", frozen=True)


class DBNovelIssueEntry(BaseModel):
    """Database representation of novel aspects for one input issue."""

    input_id: str = Field(description="Input issue ID (stored as string)")
    reasoning: DBNovelIssueReasoning

    model_config = ConfigDict(extra="forbid", frozen=True)


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
    """Database representation of an input issue with novel aspects not matched to any canonical issue.

    This is the persisted form for unknowns from grader output.
    """

    id: str = Field(description="Unknown issue ID (stored as string)")
    rationale: str = Field(description="Why this issue is novel/unknown (stored as string)")

    model_config = ConfigDict(extra="forbid", frozen=True)


class DBGraderSuccess(BaseModel):
    """Database representation of successful grader output with per-occurrence results.

    This is the persisted form, decoupled from MCP I/O types.
    All NewType IDs are stored as strings.
    """

    tag: Literal["success"] = "success"

    occurrence_results: list[DBOccurrenceResult] = Field(description="Per-occurrence grading results")

    unknowns: list[DBUnknownIssue] = Field(
        default_factory=list, description="Input issues with novel aspects not matched to canonical issues"
    )

    summary: str = Field(description="Summary rationale (stored as string)")

    model_config = ConfigDict(extra="forbid", frozen=True)


class DBGraderMaxTurnsExceeded(BaseModel):
    """Database representation of grader running out of turns."""

    tag: Literal["max_turns_exceeded"] = "max_turns_exceeded"
    max_turns: int = Field(description="Maximum turns that were allowed", gt=0)

    model_config = ConfigDict(extra="forbid", frozen=True)


class DBGraderReportedFailure(BaseModel):
    """Database representation of grader explicitly reporting it cannot complete."""

    tag: Literal["reported_failure"] = "reported_failure"
    reason: str = Field(description="Reason provided by the grader for inability to complete")

    model_config = ConfigDict(extra="forbid", frozen=True)


DBGraderOutput = Annotated[
    DBGraderSuccess | DBGraderMaxTurnsExceeded | DBGraderReportedFailure,
    Field(discriminator="tag", description="Grader output: success, max turns exceeded, or reported failure"),
]
"""Discriminated union of grader outcomes for database persistence."""
