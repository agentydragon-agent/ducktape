"""Grader data models.

Pydantic models and dataclasses for the grader subsystem.
Extracted to avoid circular dependencies with prompts.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, NewType
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
    from adgn.props.db.models import DBCriticSubmitPayload, Snapshot


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
    expected_occurrences: set[tuple[str, str]]  # (tp_id, occurrence_id) pairs that must be graded

    @classmethod
    def from_specimen_and_critique(
        cls, snapshot_orm: Snapshot, critique: DBCriticSubmitPayload, *, reviewed_files: set[Path] | None = None
    ) -> GradeValidationContext:
        """Build validation context from ORM Snapshot and critique.

        Args:
            snapshot_orm: ORM Snapshot from database (has TPs/FPs)
            critique: Critic's submitted payload (DB persistence model)
            reviewed_files: Optional set of files that were reviewed by the critic.
                If provided, only include TPs/FPs that are catchable/relevant from those files.
                If None, include all TPs/FPs.
        """
        expected_occurrences: set[tuple[str, str]] = set()

        # Filter TPs/FPs by scope if reviewed_files provided
        if reviewed_files:
            # Only include TPs where at least one occurrence is catchable from reviewed files
            allowed_tp_ids = {
                TruePositiveID(tp.tp_id)
                for tp in snapshot_orm.true_positives
                if any(should_catch_occurrence(occ, reviewed_files) for occ in tp.occurrences)
            }
            # Build expected occurrences set (filtered by catchability)
            for tp in snapshot_orm.true_positives:
                tp_id_str = str(tp.tp_id)
                if TruePositiveID(tp_id_str) not in allowed_tp_ids:
                    continue
                for occ in tp.occurrences:
                    if should_catch_occurrence(occ, reviewed_files):
                        expected_occurrences.add((tp_id_str, occ.occurrence_id))

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
            # Build expected occurrences set (all occurrences)
            for tp in snapshot_orm.true_positives:
                tp_id_str = str(tp.tp_id)
                for occ in tp.occurrences:
                    expected_occurrences.add((tp_id_str, occ.occurrence_id))

        return cls(
            allowed_tp_ids=allowed_tp_ids,
            allowed_fp_ids=allowed_fp_ids,
            allowed_input_ids={InputIssueID(issue.id) for issue in critique.issues},
            expected_occurrences=expected_occurrences,
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


class GradeSubmitInput(OpenAIStrictModeBaseModel):
    """Complete grading: coverage for all TPs/FPs/novel issues, summary.

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
      "summary": "..."
    }

    Example F — Empty critique (no issues reported):
    {
      "canonical_tp_coverage": {
        "C1": {"covered_by": {}, "recall_credit": 0.0, "rationale": "Not covered - empty"}
      },
      "canonical_fp_coverage": {},
      "novel_critique_issues": {},
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


GraderOutput = Annotated[
    GraderSuccess | GraderMaxTurnsExceeded,
    Field(discriminator="tag", description="Grader output: either success with result or max turns exceeded"),
]
"""Discriminated union of grader outcomes: success or max_turns_exceeded."""
