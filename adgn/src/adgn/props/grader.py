"""Grader MCP server and GradeSubmitPayload models.

Defines structured output used by critique grader:
(specimen canonical issues + input critique JSON → metrics + markdown summary)
AND a tiny FastMCP server that accepts exactly one submission per run via
submit_result.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator
from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from adgn.llm.rendering.rich_renderers import render_to_rich
from adgn.mcp._shared.types import SimpleOk
from adgn.props.critic import CriticSubmitPayload
from adgn.props.ids import FalsePositiveID, InputIssueID, TruePositiveID
from adgn.props.models.issue import Occurrence
from adgn.props.rationale import Rationale
from adgn.props.specimens.registry import SpecimenRecord

# Type alias for validation (0.0-1.0 range)
RatioFloat = Annotated[float, Field(ge=0.0, le=1.0)]


# TODO: Consider generic Issue[IDType] to reduce duplication
class CritiqueInputIssue(BaseModel):
    """Critique input issue with typed namespaced ID."""

    id: InputIssueID
    rationale: Rationale
    occurrences: list[Occurrence]

    model_config = ConfigDict(frozen=True)


@dataclass(frozen=True)
class GradeValidationContext:
    """Validation context with prefixed IDs.

    Use from_specimen_and_critique() factory to build from raw data.
    IDs are computed internally - caller doesn't handle prefixing.
    """

    allowed_tp_ids: set[TruePositiveID]
    allowed_fp_ids: set[FalsePositiveID]
    allowed_input_ids: set[InputIssueID]

    @classmethod
    def from_specimen_and_critique(
        cls, specimen: SpecimenRecord, critique: CriticSubmitPayload
    ) -> GradeValidationContext:
        """Build context with namespaced IDs from specimen and critique.

        INPUT BOUNDARY: This is where we construct typed namespaced IDs.
        Uses NewType wrappers for compile-time type safety.
        """
        return cls(
            allowed_tp_ids={TruePositiveID(id) for id in specimen.issues},
            allowed_fp_ids={FalsePositiveID(id) for id in specimen.false_positives},
            allowed_input_ids={InputIssueID(issue.id) for issue in critique.issues},
        )


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
    """How well a canonical true positive was covered by the input.

    Grader provides one entry per canonical TP, explaining:
    - Which input issues cover it and how much each contributes
    - Total recall credit (constrained by individual contributions)
    - Why this decision was made
    """

    covered_by: dict[InputIssueID, RatioFloat] = Field(
        default_factory=dict,
        description="Input issue IDs -> individual recall credit contributions. Empty dict = not covered.",
    )

    recall_credit: RatioFloat = Field(
        ...,
        description="Total recall credit. 0=not covered, 1=fully covered, 0.x=partial. Must satisfy: min(covered_by.values()) <= recall_credit <= sum(covered_by.values()).",
    )

    reasoning: str = Field(
        ...,
        min_length=10,
        description="Explanation of coverage decision. For matches: why semantically equivalent. For no-match: what was closest and why insufficient.",
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
    """Whether a known false positive was matched by the input.

    Grader provides one entry per canonical FP, explaining:
    - Which input issues (if any) matched it
    - Why this decision was made

    Note: FPs don't have recall_credit since they don't contribute to recall.
    Uses a set for binary matching (either matched or not).
    """

    covered_by: set[InputIssueID] = Field(
        default_factory=set, description="Input issue IDs that matched this known FP. Empty set = not matched."
    )

    reasoning: str = Field(
        ...,
        min_length=10,
        description="Explanation of match decision. For matches: why this input matches the FP. For no-match: why the input avoided this trap.",
    )

    model_config = ConfigDict(extra="forbid")


class NovelIssueReasoning(BaseModel):
    """Reasoning for novel aspects of an input issue.

    An input issue can be BOTH in covered_by lists (matching canonicals/FPs) AND have novel aspects.
    This captures what is novel/additional beyond any matched canonicals.

    Examples:
    - Pure novel: "Doesn't match any canonical. Discusses X which isn't covered."
    - Hybrid: "Matches C001 for the duplication aspect, but also raises a novel performance concern about the duplicated code."
    """

    reasoning: str = Field(
        ...,
        min_length=10,
        description="Explanation of novel aspects. For pure novel: why it doesn't match anything. For hybrid: what's novel beyond the matched canonical(s).",
    )

    model_config = ConfigDict(extra="forbid")


class ReportedIssueRatios(BaseModel):
    """Ratios of reported issues: {tp, fp, unlabeled}.

    All ratios represent weighted proportions in [0,1] and must sum to ~1.0.
    Weight by issue importance/severity (some issues are big, some are small).
    Explain weighting rationale in summary if non-obvious.
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
        """Validate that ratios sum to approximately 1.0."""
        total = self.tp + self.fp + self.unlabeled
        if not (0.99 <= total <= 1.01):
            raise ValueError(
                f"Ratios must sum to ~1.0, got {total:.3f} "
                f"(tp={self.tp:.3f}, fp={self.fp:.3f}, unlabeled={self.unlabeled:.3f})"
            )
        return self


class GradeSubmitInput(BaseModel):
    """Complete grading submission with explicit accounting for all issues.

    The grader MUST provide:
    1. Coverage for every canonical TP with recall credits
    2. Coverage for every known FP without recall credits
    3. Explicit list of novel/unlabeled input issues (those not mentioned in any covered_by)
    4. Reported issue ratios: {tp, fp, unlabeled} (weighted, must sum to ~1.0)
    5. Recall: fraction of canonical TPs covered (weighted)
    6. Summary explaining weighting, novel issues, and partial coverage

    Validation enforces completeness - submission rejected if any issue is missing or double-counted.

    IDs are plain strings (no prefixes). ID type (TP/FP/input) is implied by position in the data structure.
    """

    # Coverage for ground truth issues
    canonical_tp_coverage: dict[TruePositiveID, CanonicalTPCoverage] = Field(
        ..., description="Coverage for EVERY canonical TP. Keys are plain string IDs."
    )

    canonical_fp_coverage: dict[FalsePositiveID, CanonicalFPCoverage] = Field(
        ..., description="Coverage for EVERY known FP. Keys are plain string IDs."
    )

    # Novel/unknown input issues
    novel_critique_issues: dict[InputIssueID, NovelIssueReasoning] = Field(
        ...,
        description="Input issues with novel aspects. Keys are plain string IDs. Can be pure novel (not in any covered_by) or hybrid (appears in covered_by but has additional novel content). Empty dict if all input issues fully match canonicals/FPs.",
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
    summary: str = Field(
        ...,
        min_length=10,
        description="Markdown summary with high-level observations. MUST include weighting rationale if non-obvious, explanations for novel issues, and notes on partial coverage.",
    )

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_tp_coverage_complete(self, info: ValidationInfo) -> GradeSubmitInput:
        """Validate all canonical TPs are covered."""
        if not info.context or not isinstance(info.context, GradeValidationContext):
            return self

        ctx: GradeValidationContext = info.context
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
        if not info.context or not isinstance(info.context, GradeValidationContext):
            return self

        ctx: GradeValidationContext = info.context
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
        if not info.context or not isinstance(info.context, GradeValidationContext):
            return self

        ctx: GradeValidationContext = info.context

        # Collect all mentioned input IDs from covered_by (TP uses dict, FP uses set)
        mentioned_tp = set().union(*(cov.covered_by.keys() for cov in self.canonical_tp_coverage.values()))
        mentioned_fp = set().union(*(cov.covered_by for cov in self.canonical_fp_coverage.values()))
        mentioned = mentioned_tp | mentioned_fp

        invalid_mentioned = mentioned - ctx.allowed_input_ids
        if invalid_mentioned:
            raise ValueError(f"Invalid input IDs in covered_by: {sorted(invalid_mentioned)}")

        return self

    @model_validator(mode="after")
    def validate_novel_ids(self, info: ValidationInfo) -> GradeSubmitInput:
        """Validate all novel issue IDs are valid input IDs."""
        if not info.context or not isinstance(info.context, GradeValidationContext):
            return self

        ctx: GradeValidationContext = info.context
        extra_novel = self.novel_critique_issues.keys() - ctx.allowed_input_ids
        if extra_novel:
            raise ValueError(f"Unknown input IDs in novel_critique_issues: {sorted(extra_novel)}")

        return self

    @model_validator(mode="after")
    def validate_all_inputs_accounted(self, info: ValidationInfo) -> GradeSubmitInput:
        """Validate every input issue appears somewhere (covered_by or novel_critique_issues)."""
        if not info.context or not isinstance(info.context, GradeValidationContext):
            return self

        ctx: GradeValidationContext = info.context

        # Collect mentioned IDs from covered_by (TP uses dict, FP uses set)
        mentioned_tp = set().union(*(cov.covered_by.keys() for cov in self.canonical_tp_coverage.values()))
        mentioned_fp = set().union(*(cov.covered_by for cov in self.canonical_fp_coverage.values()))
        mentioned = mentioned_tp | mentioned_fp

        # All input IDs must be either mentioned or in novel_critique_issues
        accounted = mentioned | self.novel_critique_issues.keys()
        missing_input = ctx.allowed_input_ids - accounted
        if missing_input:
            raise ValueError(
                f"Missing input IDs: {sorted(missing_input)}. "
                f"Every input issue MUST appear in covered_by or novel_critique_issues."
            )

        return self


class GradeSubmitState:
    """Container for submitted GradeSubmitInput."""

    result: GradeSubmitInput | None = None


@dataclass(frozen=True)
class GradeInputs:
    """Single cohesive context for grading: specimen and the critique payload."""

    specimen: SpecimenRecord
    critique: CriticSubmitPayload
    round: int | None = None


def build_grader_submit_tools(mcp: FastMCP, state: GradeSubmitState, *, inputs: GradeInputs) -> None:
    """Register grader submit tool on an existing server (tools-builder pattern).

    Uses factory method to build validation context with typed IDs at INPUT boundary.
    IDs are plain strings at runtime; type safety via NewType at compile time.
    """
    # Build validation context using factory method (INPUT BOUNDARY - typed IDs created here)
    context = GradeValidationContext.from_specimen_and_critique(inputs.specimen, inputs.critique)

    @mcp.flat_model()
    async def submit_result(result: GradeSubmitInput) -> SimpleOk:
        """Submit the final grading result.

        Validates via Pydantic context.
        IDs are plain strings (NewType wrappers at runtime).
        """
        # Re-validate with context to trigger all validators
        result = GradeSubmitInput.model_validate(result.model_dump(), context=context)

        # Store the result as-is
        state.result = result
        return SimpleOk(ok=True)


def make_grader_submit_server(state: GradeSubmitState, *, name: str = "grader_submit", inputs: GradeInputs) -> FastMCP:
    """Exposes submit_result(result: GradeSubmitInput) -> {ok: True}.

    Validates returned IDs and computes metrics server-side using specimen + critique context.
    """

    mcp = FastMCP(name)
    build_grader_submit_tools(mcp, state, inputs=inputs)

    return mcp


def make_grader_submit_server_from_inputs(
    state: GradeSubmitState, *, name: str = "grader_submit", inputs: GradeInputs
) -> FastMCP:
    """Thin wrapper: pass GradeInputs through to the primary builder.

    The main make_grader_submit_server() derives allowed IDs and counts internally.
    """
    return make_grader_submit_server(state, name=name, inputs=inputs)


@render_to_rich.register
def _render_grade_submit_input(obj: GradeSubmitInput):
    """Rich renderer for GradeSubmitInput (shows coverage and summary).

    Computes derived metrics for display purposes only.
    """
    bits: list[RenderableType] = []

    # Compute derived metrics for display
    total_canonical_tps = len(obj.canonical_tp_coverage)
    total_canonical_fps = len(obj.canonical_fp_coverage)
    covered_tps = sum(1 for cov in obj.canonical_tp_coverage.values() if cov.covered_by)
    matched_fps = sum(1 for cov in obj.canonical_fp_coverage.values() if cov.covered_by)
    uncovered_tps = total_canonical_tps - covered_tps
    novel_count = len(obj.novel_critique_issues)

    # Compute fractional coverage recall from recall credits
    coverage_recall = None
    if total_canonical_tps > 0:
        # Sum recall credits, clamping each canonical's total credit to 1.0
        total_credit = sum(min(1.0, cov.recall_credit) for cov in obj.canonical_tp_coverage.values())
        coverage_recall = total_credit / total_canonical_tps

    # Main metrics table
    metrics_tbl = Table(title="Grading Metrics", show_lines=False, expand=True)
    metrics_tbl.add_column("Metric", style="cyan", no_wrap=True)
    metrics_tbl.add_column("Value", style="magenta")
    metrics_tbl.add_column("Description", style="dim")

    metrics_tbl.add_row("Recall (binary)", f"{obj.recall:.1%}", "Weighted fraction of canonicals covered")
    if coverage_recall is not None:
        metrics_tbl.add_row("Recall (fractional)", f"{coverage_recall:.1%}", "From recall credits (partial coverage)")
    metrics_tbl.add_row("TP ratio", f"{obj.reported_issue_ratios.tp:.1%}", "Reported issues matching canonicals")
    metrics_tbl.add_row("FP ratio", f"{obj.reported_issue_ratios.fp:.1%}", "Reported issues matching known FPs")
    metrics_tbl.add_row("Unlabeled ratio", f"{obj.reported_issue_ratios.unlabeled:.1%}", "Novel/unknown issues")
    bits.append(metrics_tbl)

    # Coverage breakdown table
    coverage_tbl = Table(title="Coverage Breakdown", show_lines=False, expand=True)
    coverage_tbl.add_column("Category", style="cyan", no_wrap=True)
    coverage_tbl.add_column("Covered", justify="right", style="green")
    coverage_tbl.add_column("Total", justify="right", style="blue")
    coverage_tbl.add_column("Missing", justify="right", style="red")

    coverage_tbl.add_row(
        "Canonical TPs", str(covered_tps), str(total_canonical_tps), str(uncovered_tps) if uncovered_tps > 0 else "-"
    )
    coverage_tbl.add_row("Known FPs", str(matched_fps), str(total_canonical_fps), "-")
    coverage_tbl.add_row("Novel issues", "-", str(novel_count), "-")
    bits.append(coverage_tbl)

    if obj.summary:
        bits.append(Panel(Markdown(obj.summary), title="Summary", border_style="dim"))

    body: RenderableType = bits[0] if len(bits) == 1 else Group(*bits)
    title = "[bold blue]Grader Submission[/bold blue]"
    return Panel(body, title=title, border_style="blue", padding=(1, 2))
