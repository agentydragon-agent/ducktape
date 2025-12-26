"""Grader data models.

Pydantic models and dataclasses for the grader subsystem.
Extracted to avoid circular dependencies with prompts.
"""

from __future__ import annotations

from typing import Annotated, Literal, NewType
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from openai_utils.pydantic_strict_mode import OpenAIStrictModeBaseModel
from props.ids import BaseIssueID, InputIssueID
from props.models.true_positive import FalsePositiveOccurrence, Occurrence, TruePositiveOccurrence
from props.rationale import Rationale

# =============================================================================
# Grader-specific ID Types
# =============================================================================

# These IDs are internal to the grader subsystem
# Type is implied by position in data structure (true positive keys in canonical_tp_coverage, etc.)

TruePositiveID = NewType("TruePositiveID", BaseIssueID)  # type: ignore[valid-newtype]
"""True positive ID. Compile-time distinct from other ID types, runtime is BaseIssueID string."""

FalsePositiveID = NewType("FalsePositiveID", BaseIssueID)  # type: ignore[valid-newtype]
"""False positive ID. Compile-time distinct from other ID types, runtime is BaseIssueID string."""


# =============================================================================
# Constants and Type Aliases
# =============================================================================

RatioFloat = Annotated[float, Field(ge=0.0, le=1.0)]


# =============================================================================
# Grader Input/Output Models
# =============================================================================


class GraderInput(BaseModel):
    """Input for a grader run (critic run + specimen → metrics)."""

    critic_run_id: UUID = Field(description="Database ID of critic run to grade")

    model_config = ConfigDict(extra="forbid")


# =============================================================================
# Grader Submit Models
# =============================================================================


class CritiqueInputIssue(BaseModel):
    """Critique input issue with typed namespaced ID."""

    id: InputIssueID
    rationale: Rationale
    occurrences: list[Occurrence]

    model_config = ConfigDict(frozen=True)


class TruePositiveIssue(BaseModel):
    """Canonical true positive issue with typed namespaced ID."""

    id: TruePositiveID
    rationale: Rationale
    occurrences: list[TruePositiveOccurrence]

    model_config = ConfigDict(frozen=True)


class KnownFalsePositive(BaseModel):
    """Known false positive issue with typed namespaced ID."""

    id: FalsePositiveID
    rationale: Rationale
    occurrences: list[FalsePositiveOccurrence]

    model_config = ConfigDict(frozen=True)


class GradeMetrics(BaseModel):
    """Basic grading metrics (no per-property breakdown)."""

    expected: int = Field(..., description="Number of canonical items (ground truth)")
    reported: int = Field(..., description="Number of items reported by critique")
    true_positives: int = Field(..., description="Reported items that match canonical")
    false_positive: int = Field(..., description="Reported items known to be false positives (in known-FP list)")
    unknown: int = Field(..., description="Reported items neither in canonical positives nor in known false positives")
    false_negatives: int = Field(..., description="Canonical items missing in report")
    recall: float = Field(..., description="TP / expected (known-positives); 0.0 if undefined")
    # Fractional coverage-based recall in [0,1], computed from coverage credits when expected>0
    coverage_recall: float | None = Field(
        default=None,
        description=(
            "Fractional recall in [0,1] derived from per-canonical coverage credits "
            "(sum of credits per canonical clamped to 1.0, averaged over expected)."
        ),
    )

    model_config = ConfigDict(extra="forbid")


# =============================================================================
# Per-Occurrence Grading Models (V2)
# =============================================================================


class OccurrenceMatch(OpenAIStrictModeBaseModel):
    """Match between an input issue and a canonical occurrence.

    Represents which critique issues contributed to finding a specific occurrence,
    and how much credit each should receive.
    """

    input_id: InputIssueID = Field(description="Input issue ID that matched")
    credit: RatioFloat = Field(description="Credit for this match (0.0-1.0)")

    model_config = ConfigDict(frozen=True)


class OccurrenceResult(OpenAIStrictModeBaseModel):
    """Grading result for a single occurrence of a true positive.

    Tracks whether this specific occurrence was found, which critique issues
    matched it, and the rationale for the grading decision.
    """

    tp_id: TruePositiveID = Field(description="True positive ID this occurrence belongs to")
    occurrence_id: str = Field(description="Unique identifier for this occurrence within the TP")

    found_credit: RatioFloat = Field(
        description="Overall credit for finding this occurrence (0.0=not found, 1.0=fully found, 0.x=partial)"
    )

    matched_by: list[OccurrenceMatch] = Field(
        description="Which input issues matched this occurrence and their individual credits. Empty if not found."
    )

    rationale: Rationale = Field(
        description=(
            "Explanation of grading decision with code references. "
            "For matches: why semantically equivalent (include code inspection if ranges differ). "
            "For partial: what was covered and missed. "
            "For no-match: what was closest and why insufficient."
        )
    )

    model_config = ConfigDict(frozen=True)


# =============================================================================
# Unknown Issue Models
# =============================================================================


class UnknownIssue(OpenAIStrictModeBaseModel):
    """Input issue with novel aspects not matched to any canonical issue.

    Represents critique issues that don't match any known true positives or false positives.
    These may be genuinely novel findings or issues that fall outside the canonical set.
    """

    input_id: InputIssueID = Field(description="Input issue ID from critique")
    rationale: Rationale = Field(description="Why this issue is novel/unknown and doesn't match canonical issues")

    model_config = ConfigDict(frozen=True)


# =============================================================================
# Grader Output Models
# =============================================================================


class GraderSuccess(BaseModel):
    """Successful grader output with per-occurrence results."""

    tag: Literal["success"] = "success"

    occurrence_results: list[OccurrenceResult] = Field(
        description="Per-occurrence grading results. One entry per catchable occurrence."
    )

    unknowns: list[UnknownIssue] = Field(
        default_factory=list, description="Input issues with novel aspects not matched to canonical issues (TPs or FPs)"
    )

    summary: Rationale = Field(description="High-level summary of grading. Cross-cutting patterns, overall assessment.")

    model_config = ConfigDict(frozen=True)


class GraderMaxTurnsExceeded(BaseModel):
    """Grader ran out of turns before completing."""

    tag: Literal["max_turns_exceeded"] = "max_turns_exceeded"
    max_turns: int = Field(description="Maximum turns that were allowed", gt=0)

    model_config = ConfigDict(frozen=True)


class GraderReportedFailure(BaseModel):
    """Grader explicitly reported that it cannot complete grading."""

    tag: Literal["reported_failure"] = "reported_failure"
    reason: str = Field(description="Reason provided by the grader for inability to complete")

    model_config = ConfigDict(frozen=True)


GraderOutput = Annotated[
    GraderSuccess | GraderMaxTurnsExceeded | GraderReportedFailure,
    Field(discriminator="tag", description="Grader output: success, max turns exceeded, or reported failure"),
]
"""Discriminated union of grader outcomes: success, max_turns_exceeded, or reported_failure."""
