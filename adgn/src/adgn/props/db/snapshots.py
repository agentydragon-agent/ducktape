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


class DBTruePositiveOccurrence(BaseModel):
    """Database representation of a true positive occurrence."""

    files: dict[str, list[DBLineRange] | None] = Field(description="File paths (as strings) mapped to line ranges")
    note: str | None = Field(default=None)
    expect_caught_from: list[list[str]] = Field(
        description="Minimal file sets for detection (list of alternatives, each alternative is list of paths)"
    )

    model_config = ConfigDict(extra="forbid", frozen=True)


class DBFalsePositiveOccurrence(BaseModel):
    """Database representation of a false positive occurrence."""

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
    """Database representation of critic submit payload."""

    issues: list[DBReportedIssue] = Field(description="Issues found")
    notes_md: str | None = Field(default=None, description="Optional Markdown notes")

    model_config = ConfigDict(extra="forbid", frozen=True)


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


class DBReportedIssueRatios(BaseModel):
    """Database representation of weighted ratios {tp, fp, unlabeled}."""

    tp: float = Field(ge=0.0, le=1.0, description="Ratio matching canonical TPs")
    fp: float = Field(ge=0.0, le=1.0, description="Ratio matching known FPs")
    unlabeled: float = Field(ge=0.0, le=1.0, description="Ratio that is novel/unlabeled")

    model_config = ConfigDict(extra="forbid", frozen=True)


class DBGraderOutput(BaseModel):
    """Database representation of grader output.

    This is the persisted form, decoupled from MCP I/O types.
    All NewType IDs are stored as strings.
    """

    canonical_tp_coverage: list[DBTPCoverageEntry]
    canonical_fp_coverage: list[DBFPCoverageEntry]
    novel_critique_issues: list[DBNovelIssueEntry]
    reported_issue_ratios: DBReportedIssueRatios | None
    recall: float = Field(ge=0.0, le=1.0)
    summary: str = Field(description="Summary rationale (stored as string)")

    model_config = ConfigDict(extra="forbid", frozen=True)
