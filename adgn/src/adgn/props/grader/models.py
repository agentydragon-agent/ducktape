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

from adgn.openai_utils.pydantic_strict_mode import OpenAIStrictModeBaseModel
from adgn.props.ids import BaseIssueID, InputIssueID, SnapshotSlug
from adgn.props.models.true_positive import (
    FalsePositiveOccurrence,
    Occurrence,
    TruePositiveOccurrence,
    should_catch_occurrence,
    should_show_fp_occurrence,
)
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
                If provided, only include TPs/FPs that are catchable/relevant from those files.
                If None, include all TPs/FPs.
        """
        # Filter TPs/FPs by scope if reviewed_files provided
        if reviewed_files:
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
        """Fractional coverage-based recall, or None if no canonical TPs."""
        if not self.grade.canonical_tp_coverage:
            return None
        total_credit = sum(entry.coverage.recall_credit for entry in self.grade.canonical_tp_coverage)
        return total_credit / len(self.grade.canonical_tp_coverage)


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


class IssueCoverageEntry(OpenAIStrictModeBaseModel):
    """Single input issue's contribution to canonical coverage."""

    input_id: InputIssueID = Field(description="Input issue ID")
    credit: RatioFloat = Field(description="Individual recall credit contribution")

    model_config = ConfigDict(frozen=True)


class CanonicalTPCoverage(OpenAIStrictModeBaseModel):
    """Coverage of a canonical TP: which inputs matched, recall credit, rationale."""

    covered_by: list[IssueCoverageEntry] = Field(description="Input issue contributions. Empty list = not covered.")

    recall_credit: RatioFloat = Field(
        description="Total recall credit. 0=not covered, 1=fully covered, 0.x=partial. Must satisfy: min(credits) <= recall_credit <= sum(credits)."
    )

    rationale: Rationale = Field(
        description=(
            "Explanation of coverage decision with code references. "
            "For matches: why semantically equivalent (include code inspection details if line ranges differ). "
            "For partial coverage: what was covered and what was missed. "
            "For no-match: what was closest and why insufficient."
        )
    )

    model_config = ConfigDict(extra="forbid")

    @classmethod
    def from_covered_by_dict(cls, covered_by: dict[InputIssueID, RatioFloat], **kwargs) -> CanonicalTPCoverage:
        """Construct from covered_by dict (convenience for migration/tests)."""
        entries = [IssueCoverageEntry(input_id=k, credit=v) for k, v in covered_by.items()]
        return cls(covered_by=entries, **kwargs)

    def covered_by_dict(self) -> dict[InputIssueID, RatioFloat]:
        """Get covered_by as dict (for backwards compatibility)."""
        return {entry.input_id: entry.credit for entry in self.covered_by}

    @model_validator(mode="after")
    def validate_recall_credit_bounds(self) -> CanonicalTPCoverage:
        """Validate that recall_credit is bounded by individual contributions."""
        if not self.covered_by:
            # Not covered: recall_credit must be 0
            if self.recall_credit != 0.0:
                raise ValueError(f"covered_by is empty but recall_credit is {self.recall_credit}, expected 0.0")
            return self

        individual_credits = [entry.credit for entry in self.covered_by]
        min_credit = min(individual_credits)
        sum_credit = sum(individual_credits)

        if not (min_credit <= self.recall_credit <= sum_credit):
            raise ValueError(
                f"recall_credit {self.recall_credit} must be in [{min_credit}, {sum_credit}] "
                f"(min and sum of individual contributions: {self.covered_by_dict()})"
            )
        return self


class CanonicalFPCoverage(OpenAIStrictModeBaseModel):
    """Coverage of a known FP: which inputs matched (if any), rationale."""

    covered_by: list[InputIssueID] = Field(
        description="Input issue IDs that matched this known FP. Empty list = not matched."
    )

    rationale: Rationale = Field(
        description="Explanation of match decision. For matches: why this input matches the FP. For no-match: why the input avoided this trap."
    )

    model_config = ConfigDict(extra="forbid")


class NovelIssueReasoning(OpenAIStrictModeBaseModel):
    """Rationale for novel aspects beyond matched canonicals/FPs."""

    rationale: Rationale = Field(
        description=(
            "Explanation of novel aspects with code references. "
            "For pure novel: why it doesn't match anything (reference inspected code locations). "
            "For hybrid: what's novel beyond the matched canonical(s)."
        )
    )

    model_config = ConfigDict(extra="forbid")


class TPCoverageEntry(OpenAIStrictModeBaseModel):
    """Coverage for one canonical true positive."""

    canonical_id: TruePositiveID = Field(description="Canonical TP ID")
    # Note: no description on $ref fields - OpenAI strict mode doesn't allow it
    coverage: CanonicalTPCoverage

    model_config = ConfigDict(extra="forbid", frozen=True)


class FPCoverageEntry(OpenAIStrictModeBaseModel):
    """Coverage for one known false positive."""

    canonical_id: FalsePositiveID = Field(description="Known FP ID")
    # Note: no description on $ref fields - OpenAI strict mode doesn't allow it
    coverage: CanonicalFPCoverage

    model_config = ConfigDict(extra="forbid", frozen=True)


class NovelIssueEntry(OpenAIStrictModeBaseModel):
    """Novel aspects for one input issue."""

    input_id: InputIssueID = Field(description="Input issue ID with novel aspects")
    # Note: no description on $ref fields - OpenAI strict mode doesn't allow it
    reasoning: NovelIssueReasoning

    model_config = ConfigDict(extra="forbid", frozen=True)


class ReportedIssueRatios(OpenAIStrictModeBaseModel):
    """Weighted ratios {tp, fp, unlabeled} in [0,1], must sum to ~1.0.

    Note: This model should only be instantiated when there are actually reported issues.
    For empty critiques (no issues reported), use None instead of creating a zero-valued instance.
    """

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
        """Validate that ratios sum to approximately 1.0.

        Note: This validator does not allow all-zero ratios. For empty critiques,
        reported_issue_ratios should be None, not ReportedIssueRatios(0, 0, 0).
        """
        total = self.tp + self.fp + self.unlabeled

        if not (1.0 - RATIO_SUM_TOLERANCE <= total <= 1.0 + RATIO_SUM_TOLERANCE):
            raise ValueError(
                f"Ratios must sum to ~1.0, got {total:.3f} "
                f"(tp={self.tp:.3f}, fp={self.fp:.3f}, unlabeled={self.unlabeled:.3f}). "
                f"For empty critiques with no reported issues, use None instead of zero-valued ratios."
            )
        return self


class GradeSubmitInput(OpenAIStrictModeBaseModel):
    """Complete grading: coverage for all TPs/FPs/novel issues, metrics, summary.

    Validation enforces completeness. Weight issues fractionally by severity/size.
    Put reasoning in narrowest applicable field; avoid duplication.

    Examples:

    Example A — One input issue spans multiple canonical items (C1, C2):
    {
      "canonical_tp_coverage": {
        "C1": {"covered_by": {"I1": 1.0}, "recall_credit": 1.0, "rationale": "..."},
        "C2": {"covered_by": {"I1": 1.0}, "recall_credit": 1.0, "rationale": "..."}
      },
      "canonical_fp_coverage": {},
      "novel_critique_issues": {},
      "reported_issue_ratios": {"tp": 1.0, "fp": 0.0, "unlabeled": 0.0},
      "recall": 1.0,
      "summary": "..."
    }

    Example B — Input overlaps TP and FP (hybrid):
    {
      "canonical_tp_coverage": {
        "C1": {"covered_by": {"I1": 1.0}, "recall_credit": 1.0, "rationale": "..."}
      },
      "canonical_fp_coverage": {
        "F1": {"covered_by": ["I1"], "rationale": "..."}
      },
      "novel_critique_issues": {},
      "reported_issue_ratios": {"tp": 0.5, "fp": 0.5, "unlabeled": 0.0},
      "recall": 1.0,
      "summary": "..."
    }

    Example C — Multiple inputs partially cover one canonical:
    {
      "canonical_tp_coverage": {
        "C1": {
          "covered_by": {"I1": 0.6, "I2": 0.3},
          "recall_credit": 0.8,
          "rationale": "I1 covers 6/10 occurrences, I2 covers 3/10 with some overlap"
        }
      },
      "canonical_fp_coverage": {},
      "novel_critique_issues": {},
      "reported_issue_ratios": {"tp": 1.0, "fp": 0.0, "unlabeled": 0.0},
      "recall": 0.8,
      "summary": "..."
    }

    Example D — Hybrid issue (matches canonical AND has novel aspects):
    {
      "canonical_tp_coverage": {
        "C1": {"covered_by": {"I1": 1.0}, "recall_credit": 1.0, "rationale": "..."}
      },
      "canonical_fp_coverage": {},
      "novel_critique_issues": {
        "I1": {"rationale": "Matches C1 for duplication, but adds novel O(n²) concern"}
      },
      "reported_issue_ratios": {"tp": 0.7, "fp": 0.0, "unlabeled": 0.3},
      "recall": 1.0,
      "summary": "..."
    }

    Example E — Pure novel issue (no canonical match):
    {
      "canonical_tp_coverage": {
        "C1": {"covered_by": {}, "recall_credit": 0.0, "rationale": "Not covered..."}
      },
      "canonical_fp_coverage": {},
      "novel_critique_issues": {
        "I2": {"rationale": "Pure novel. Discusses mount failure handling not in canonical"}
      },
      "reported_issue_ratios": {"tp": 0.0, "fp": 0.0, "unlabeled": 1.0},
      "recall": 0.0,
      "summary": "..."
    }

    Example F — Empty critique (no issues reported):
    {
      "canonical_tp_coverage": {
        "C1": {"covered_by": {}, "recall_credit": 0.0, "rationale": "Not covered - empty"}
      },
      "canonical_fp_coverage": {},
      "novel_critique_issues": {},
      "reported_issue_ratios": null,
      "recall": 0.0,
      "summary": "Critique reported no issues. All canonical issues uncovered."
    }
    """

    # Coverage for ground truth issues
    canonical_tp_coverage: list[TPCoverageEntry] = Field(
        ..., description="Coverage for EVERY canonical TP. Must include all canonical TPs."
    )

    canonical_fp_coverage: list[FPCoverageEntry] = Field(
        ..., description="Coverage for EVERY known FP. Must include all known FPs."
    )

    # Novel/unknown input issues
    novel_critique_issues: list[NovelIssueEntry] = Field(
        ...,
        description="Input issues with novel aspects. Can be pure novel (not in any covered_by) or hybrid (appears in covered_by but has additional novel content). Empty list if all input issues fully match canonicals/FPs.",
    )

    # Metrics
    reported_issue_ratios: ReportedIssueRatios | None = Field(
        ...,
        description="Ratios of reported issues: {tp, fp, unlabeled}. Weighted by importance/severity. Must sum to ~1.0. Use None when critique is empty (no issues reported).",
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

    @classmethod
    def from_canonical_tp_coverage_dict(
        cls, canonical_tp_coverage: dict[TruePositiveID, CanonicalTPCoverage], **kwargs
    ) -> GradeSubmitInput:
        """Construct from canonical_tp_coverage dict (convenience for migration)."""
        entries = [TPCoverageEntry(canonical_id=k, coverage=v) for k, v in canonical_tp_coverage.items()]
        return cls(canonical_tp_coverage=entries, **kwargs)

    def canonical_tp_coverage_dict(self) -> dict[TruePositiveID, CanonicalTPCoverage]:
        """Get canonical_tp_coverage as dict (for backwards compatibility)."""
        return {entry.canonical_id: entry.coverage for entry in self.canonical_tp_coverage}

    def canonical_fp_coverage_dict(self) -> dict[FalsePositiveID, CanonicalFPCoverage]:
        """Get canonical_fp_coverage as dict (for backwards compatibility)."""
        return {entry.canonical_id: entry.coverage for entry in self.canonical_fp_coverage}

    def novel_critique_issues_dict(self) -> dict[InputIssueID, NovelIssueReasoning]:
        """Get novel_critique_issues as dict (for backwards compatibility)."""
        return {entry.input_id: entry.reasoning for entry in self.novel_critique_issues}

    def _get_validation_context(self, info: ValidationInfo) -> GradeValidationContext | None:
        """Get validation context if available and correct type."""
        if info.context is None:
            return None
        ctx = info.context.get("grade_validation_context")
        return ctx if isinstance(ctx, GradeValidationContext) else None

    @property
    def _mentioned_tp_ids(self) -> set[InputIssueID]:
        """Input IDs mentioned in canonical TP coverage."""
        return set().union(*(entry.coverage.covered_by_dict().keys() for entry in self.canonical_tp_coverage))

    @property
    def _mentioned_fp_ids(self) -> set[InputIssueID]:
        """Input IDs mentioned in canonical FP coverage."""
        result: set[InputIssueID] = set()
        for entry in self.canonical_fp_coverage:
            result.update(entry.coverage.covered_by)
        return result

    @model_validator(mode="after")
    def validate_tp_coverage_complete(self, info: ValidationInfo) -> GradeSubmitInput:
        """Validate all canonical TPs are covered."""
        if (ctx := self._get_validation_context(info)) is None:
            return self
        covered_tp_ids = {entry.canonical_id for entry in self.canonical_tp_coverage}
        if missing_tp := ctx.allowed_tp_ids - covered_tp_ids:
            raise ValueError(f"Missing canonical TP coverage for: {sorted(missing_tp)}")

        if extra_tp := covered_tp_ids - ctx.allowed_tp_ids:
            raise ValueError(f"Unknown canonical TP IDs: {sorted(extra_tp)}")

        return self

    @model_validator(mode="after")
    def validate_fp_coverage_complete(self, info: ValidationInfo) -> GradeSubmitInput:
        """Validate all known FPs are covered."""
        if (ctx := self._get_validation_context(info)) is None:
            return self
        covered_fp_ids = {entry.canonical_id for entry in self.canonical_fp_coverage}
        if missing_fp := ctx.allowed_fp_ids - covered_fp_ids:
            raise ValueError(f"Missing FP coverage for: {sorted(missing_fp)}")

        if extra_fp := covered_fp_ids - ctx.allowed_fp_ids:
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
        novel_input_ids = {entry.input_id for entry in self.novel_critique_issues}
        if extra_novel := novel_input_ids - ctx.allowed_input_ids:
            raise ValueError(f"Unknown input IDs in novel_critique_issues: {sorted(extra_novel)}")

        return self

    @model_validator(mode="after")
    def validate_all_inputs_accounted(self, info: ValidationInfo) -> GradeSubmitInput:
        """Validate every input issue appears somewhere (covered_by or novel_critique_issues)."""
        if (ctx := self._get_validation_context(info)) is None:
            return self

        # All input IDs must be either mentioned or in novel_critique_issues
        novel_input_ids = {entry.input_id for entry in self.novel_critique_issues}
        if missing_input := ctx.allowed_input_ids - (self._mentioned_tp_ids | self._mentioned_fp_ids | novel_input_ids):
            raise ValueError(
                f"Missing input IDs: {sorted(missing_input)}. "
                f"Every input issue MUST appear in covered_by or novel_critique_issues."
            )

        return self

    @model_validator(mode="after")
    def validate_empty_critique_ratios(self, info: ValidationInfo) -> GradeSubmitInput:
        """Validate None ratios only allowed for truly empty critique."""
        if (ctx := self._get_validation_context(info)) is None:
            return self

        has_input_issues = len(ctx.allowed_input_ids) > 0

        if self.reported_issue_ratios is None and has_input_issues:
            raise ValueError(
                f"Cannot have None reported_issue_ratios when critique has {len(ctx.allowed_input_ids)} input issues. "
                f"Use None only for empty critiques with no reported issues."
            )

        if self.reported_issue_ratios is not None and not has_input_issues:
            raise ValueError("Must use None for reported_issue_ratios when critique has no input issues.")

        return self
