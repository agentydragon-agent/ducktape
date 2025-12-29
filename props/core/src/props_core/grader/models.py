"""Grader data models.

Pydantic models and dataclasses for the grader subsystem.
Extracted to avoid circular dependencies with prompts.
"""

from __future__ import annotations

from typing import NewType
from uuid import UUID

from props_core.ids import BaseIssueID, InputIssueID
from props_core.models.true_positive import FalsePositiveOccurrence, Occurrence, TruePositiveOccurrence
from props_core.rationale import Rationale
from pydantic import BaseModel, ConfigDict, Field

from openai_utils.pydantic_strict_mode import OpenAIStrictModeBaseModel

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
# Grader Input Models
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
