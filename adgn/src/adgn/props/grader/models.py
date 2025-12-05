"""Grader data models.

Pydantic models and dataclasses for the grader subsystem.
Extracted to avoid circular dependencies with prompts.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, NewType
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

from adgn.props.ids import BaseIssueID, InputIssueID, SnapshotSlug
from adgn.props.models.true_positive import FalsePositiveOccurrence, Occurrence, TruePositiveOccurrence
from adgn.props.rationale import Rationale

if TYPE_CHECKING:
    from adgn.props.critic.models import CriticSubmitPayload
    from adgn.props.db.models import Snapshot


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

# Feature flag: filter TPs/FPs by critic scope using expect_caught_from
FILTER_TPS_BY_CRITIC_SCOPE = True

RATIO_SUM_TOLERANCE = 0.01  # Allow ±0.01 deviation from 1.0
RatioFloat = Annotated[float, Field(ge=0.0, le=1.0)]


# =============================================================================
# Validation Context
# =============================================================================


@dataclass(frozen=True)
class GradeValidationContext:
    """Validation context: allowed IDs for grading.

    Context key: "grade_validation_context"
    """

    allowed_tp_ids: set[TruePositiveID]
    allowed_fp_ids: set[FalsePositiveID]
    allowed_input_ids: set[InputIssueID]

    @classmethod
    def from_specimen_and_critique(
        cls, snapshot_orm: Snapshot, critique: CriticSubmitPayload, *, reviewed_files: set[Path] | None = None
    ) -> GradeValidationContext:
        """Build validation context from ORM Snapshot and critique.

        Args:
            snapshot_orm: ORM Snapshot from database (has TPs/FPs)
            critique: Critic's submitted payload
            reviewed_files: Optional set of files that were reviewed by the critic.
                If provided and FILTER_TPS_BY_CRITIC_SCOPE is True, only include
                TPs/FPs that are catchable/relevant from those files.
        """
        from adgn.props.models.true_positive import should_catch_occurrence, should_show_fp_occurrence

        # Filter TPs/FPs by scope if enabled and reviewed_files provided
        if FILTER_TPS_BY_CRITIC_SCOPE and reviewed_files:
            # Only include TPs where at least one occurrence is catchable from reviewed files
            allowed_tp_ids = {
                TruePositiveID(tp.tp_id)
                for tp in snapshot_orm.true_positives
                if any(should_catch_occurrence(occ, reviewed_files) for occ in tp.occurrences)
            }
            # Only include FPs where at least one occurrence is relevant to reviewed files
            allowed_fp_ids = {
                FalsePositiveID(fp.fp_id)
                for fp in snapshot_orm.false_positives
                if any(should_show_fp_occurrence(occ, reviewed_files) for occ in fp.occurrences)
            }
        else:
            # No filtering: include all TPs/FPs
            allowed_tp_ids = {TruePositiveID(tp.tp_id) for tp in snapshot_orm.true_positives}
            allowed_fp_ids = {FalsePositiveID(fp.fp_id) for fp in snapshot_orm.false_positives}

        return cls(
            allowed_tp_ids=allowed_tp_ids,
            allowed_fp_ids=allowed_fp_ids,
            allowed_input_ids={InputIssueID(issue.id) for issue in critique.issues},
        )


# =============================================================================
# Grader Input/Output Models
# =============================================================================


class GraderInput(BaseModel):
    """Input for a grader run (critique + specimen → metrics)."""

    snapshot_slug: SnapshotSlug = Field(description="Snapshot being graded")
    critique_id: UUID = Field(description="Database ID of critique to grade")
    prompt_optimization_run_id: UUID | None = Field(
        default=None, description="Optional link to prompt optimization session"
    )

    model_config = ConfigDict(extra="forbid")


class GraderOutput(BaseModel):
    """Grader run output: metrics and detailed coverage."""

    grade: GradeSubmitInput = Field(description="Full grading result with detailed coverage and metrics")

    model_config = ConfigDict(extra="forbid")

    @property
    def recall(self) -> float:
        """Binary recall (0-1) from the grading result."""
        return self.grade.recall

    @property
    def coverage_recall(self) -> float | None:
        """Fractional recall from recall credits (0-1), if computed."""
        total_canonical_tps = len(self.grade.canonical_tp_coverage)
        if total_canonical_tps == 0:
            return None
        # Sum recall credits, clamping each canonical's total credit to 1.0
        total_credit = sum(min(1.0, cov.recall_credit) for cov in self.grade.canonical_tp_coverage.values())
        return total_credit / total_canonical_tps


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
    precision: float = Field(..., description="TP / (TP + false_positive + unknown); 0.0 if undefined")
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


class CanonicalTPCoverage(BaseModel):
    """Coverage of a canonical TP: which inputs matched, recall credit, rationale."""

    covered_by: dict[InputIssueID, RatioFloat] = Field(
        default_factory=dict,
        description="Input issue IDs -> individual recall credit contributions. Empty dict = not covered.",
    )

    recall_credit: RatioFloat = Field(
        ...,
        description="Total recall credit. 0=not covered, 1=fully covered, 0.x=partial. Must satisfy: min(covered_by.values()) <= recall_credit <= sum(covered_by.values()).",
    )

    rationale: Rationale = Field(
        description="Explanation of coverage decision. For matches: why semantically equivalent. For no-match: what was closest and why insufficient."
    )

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_recall_credit_bounds(self) -> CanonicalTPCoverage:
        """Validate that recall_credit is bounded by individual contributions."""
        if not self.covered_by:
            # Not covered: recall_credit must be 0
            if self.recall_credit != 0.0:
                raise ValueError(f"covered_by is empty but recall_credit is {self.recall_credit}, expected 0.0")
            return self

        individual_credits = list(self.covered_by.values())
        min_credit = min(individual_credits)
        sum_credit = sum(individual_credits)

        if not (min_credit <= self.recall_credit <= sum_credit):
            raise ValueError(
                f"recall_credit {self.recall_credit} must be in [{min_credit}, {sum_credit}] "
                f"(min and sum of individual contributions: {dict(self.covered_by)})"
            )
        return self


class CanonicalFPCoverage(BaseModel):
    """Coverage of a known FP: which inputs matched (if any), rationale."""

    covered_by: set[InputIssueID] = Field(
        default_factory=set, description="Input issue IDs that matched this known FP. Empty set = not matched."
    )

    rationale: Rationale = Field(
        description="Explanation of match decision. For matches: why this input matches the FP. For no-match: why the input avoided this trap."
    )

    model_config = ConfigDict(extra="forbid")


class NovelIssueReasoning(BaseModel):
    """Rationale for novel aspects beyond matched canonicals/FPs."""

    rationale: Rationale = Field(
        description="Explanation of novel aspects. For pure novel: why it doesn't match anything. For hybrid: what's novel beyond the matched canonical(s)."
    )

    model_config = ConfigDict(extra="forbid")


class ReportedIssueRatios(BaseModel):
    """Weighted ratios {tp, fp, unlabeled} in [0,1], must sum to ~1.0."""

    tp: float = Field(..., ge=0.0, le=1.0, description="Ratio of reported issue weight that matches canonical TPs")

    fp: float = Field(..., ge=0.0, le=1.0, description="Ratio of reported issue weight that matches known FPs")

    unlabeled: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Ratio of reported issue weight that is novel/unlabeled (doesn't match any canonical)",
    )

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_ratios_sum(self) -> ReportedIssueRatios:
        """Validate that ratios sum to approximately 1.0."""
        if not (
            1.0 - RATIO_SUM_TOLERANCE <= (total := self.tp + self.fp + self.unlabeled) <= 1.0 + RATIO_SUM_TOLERANCE
        ):
            raise ValueError(
                f"Ratios must sum to ~1.0, got {total:.3f} "
                f"(tp={self.tp:.3f}, fp={self.fp:.3f}, unlabeled={self.unlabeled:.3f})"
            )
        return self


class GradeSubmitInput(BaseModel):
    """Complete grading: coverage for all TPs/FPs/novel issues, metrics, summary.

    Validation enforces completeness. Weight issues fractionally by severity/size.
    Put reasoning in narrowest applicable field; avoid duplication.
    """

    # Coverage for ground truth issues
    canonical_tp_coverage: dict[TruePositiveID, CanonicalTPCoverage] = Field(
        ..., description="Coverage for EVERY canonical TP. Keys are typed IDs (TruePositiveID)."
    )

    canonical_fp_coverage: dict[FalsePositiveID, CanonicalFPCoverage] = Field(
        ..., description="Coverage for EVERY known FP. Keys are typed IDs (FalsePositiveID)."
    )

    # Novel/unknown input issues
    novel_critique_issues: dict[InputIssueID, NovelIssueReasoning] = Field(
        ...,
        description="Input issues with novel aspects. Keys are typed IDs (InputIssueID). Can be pure novel (not in any covered_by) or hybrid (appears in covered_by but has additional novel content). Empty dict if all input issues fully match canonicals/FPs.",
    )

    # Metrics
    reported_issue_ratios: ReportedIssueRatios = Field(
        ...,
        description="Ratios of reported issues: {tp, fp, unlabeled}. Weighted by importance/severity. Must sum to ~1.0.",
    )

    recall: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Fraction [0,1] of canonical TPs that were covered. Weighted by issue importance/severity. Explain weighting in summary if non-obvious.",
    )

    # Required summary
    summary: Rationale = Field(
        description="Markdown summary with high-level observations. Use for cross-cutting patterns, weighting rationale (if non-obvious), or specimen-level notes. DO NOT repeat per-issue details already in rationale fields—assume reader sees entire object."
    )

    model_config = ConfigDict(extra="forbid")

    def _get_validation_context(self, info: ValidationInfo) -> GradeValidationContext | None:
        """Get validation context if available and correct type."""
        if info.context is None:
            return None
        ctx = info.context.get("grade_validation_context")
        return ctx if isinstance(ctx, GradeValidationContext) else None

    @property
    def _mentioned_tp_ids(self) -> set[InputIssueID]:
        """Input IDs mentioned in canonical TP coverage."""
        return set().union(*(cov.covered_by.keys() for cov in self.canonical_tp_coverage.values()))

    @property
    def _mentioned_fp_ids(self) -> set[InputIssueID]:
        """Input IDs mentioned in canonical FP coverage."""
        return set().union(*(cov.covered_by for cov in self.canonical_fp_coverage.values()))

    @model_validator(mode="after")
    def validate_tp_coverage_complete(self, info: ValidationInfo) -> GradeSubmitInput:
        """Validate all canonical TPs are covered."""
        if (ctx := self._get_validation_context(info)) is None:
            return self
        missing_tp = ctx.allowed_tp_ids - self.canonical_tp_coverage.keys()
        if missing_tp:
            raise ValueError(f"Missing canonical TP coverage for: {sorted(missing_tp)}")

        extra_tp = self.canonical_tp_coverage.keys() - ctx.allowed_tp_ids
        if extra_tp:
            raise ValueError(f"Unknown canonical TP IDs: {sorted(extra_tp)}")

        return self

    @model_validator(mode="after")
    def validate_fp_coverage_complete(self, info: ValidationInfo) -> GradeSubmitInput:
        """Validate all known FPs are covered."""
        if (ctx := self._get_validation_context(info)) is None:
            return self
        missing_fp = ctx.allowed_fp_ids - self.canonical_fp_coverage.keys()
        if missing_fp:
            raise ValueError(f"Missing FP coverage for: {sorted(missing_fp)}")

        extra_fp = self.canonical_fp_coverage.keys() - ctx.allowed_fp_ids
        if extra_fp:
            raise ValueError(f"Unknown FP IDs: {sorted(extra_fp)}")

        return self

    @model_validator(mode="after")
    def validate_covered_by_ids(self, info: ValidationInfo) -> GradeSubmitInput:
        """Validate all IDs mentioned in covered_by are valid input IDs."""
        if (ctx := self._get_validation_context(info)) is None:
            return self

        if invalid_tp := self._mentioned_tp_ids - ctx.allowed_input_ids:
            raise ValueError(f"Invalid input IDs in TP covered_by: {sorted(invalid_tp)}")

        if invalid_fp := self._mentioned_fp_ids - ctx.allowed_input_ids:
            raise ValueError(f"Invalid input IDs in FP covered_by: {sorted(invalid_fp)}")

        return self

    @model_validator(mode="after")
    def validate_novel_ids(self, info: ValidationInfo) -> GradeSubmitInput:
        """Validate all novel issue IDs are valid input IDs."""
        if (ctx := self._get_validation_context(info)) is None:
            return self
        extra_novel = self.novel_critique_issues.keys() - ctx.allowed_input_ids
        if extra_novel:
            raise ValueError(f"Unknown input IDs in novel_critique_issues: {sorted(extra_novel)}")

        return self

    @model_validator(mode="after")
    def validate_all_inputs_accounted(self, info: ValidationInfo) -> GradeSubmitInput:
        """Validate every input issue appears somewhere (covered_by or novel_critique_issues)."""
        if (ctx := self._get_validation_context(info)) is None:
            return self

        # All input IDs must be either mentioned or in novel_critique_issues
        missing_input = ctx.allowed_input_ids - (
            self._mentioned_tp_ids | self._mentioned_fp_ids | self.novel_critique_issues.keys()
        )
        if missing_input:
            raise ValueError(
                f"Missing input IDs: {sorted(missing_input)}. "
                f"Every input issue MUST appear in covered_by or novel_critique_issues."
            )

        return self
