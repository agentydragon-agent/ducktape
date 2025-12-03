"""Grader MCP server and GradeSubmitPayload models.

Defines structured output used by critique grader:
(specimen canonical issues + input critique JSON → metrics + markdown summary)
AND a tiny FastMCP server that accepts exactly one submission per run via
submit_result.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING, Annotated, cast
from uuid import UUID, uuid4

from fastmcp.client import Client
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator
from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from sqlalchemy.orm import Session

from adgn.agent.agent import MiniCodex
from adgn.agent.handler import BaseHandler
from adgn.agent.loop_control import RequireAnyTool
from adgn.agent.reducer import AbortIf
from adgn.llm.rendering.rich_renderers import render_to_rich
from adgn.mcp._shared.constants import GRADER_SUBMIT_SERVER_NAME
from adgn.mcp._shared.naming import build_mcp_function
from adgn.mcp._shared.types import SimpleOk
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.compositor.setup import mount_standard_inproc_servers
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP
from adgn.openai_utils.model import OpenAIModelProto
from adgn.openai_utils.types import ReasoningSummary
from adgn.props.agent_setup import build_props_handlers
from adgn.props.critic import CriticSubmitPayload
from adgn.props.db import get_session
from adgn.props.db.models import Critique, GraderRun as DBGraderRun
from adgn.props.docker_env import properties_docker_spec
from adgn.props.ids import FalsePositiveID, InputIssueID, SpecimenSlug, TruePositiveID
from adgn.props.models.issue import Occurrence
from adgn.props.paths import SpecimenRelativePath
from adgn.props.rationale import Rationale
from adgn.props.specimens.hydrated import HydratedSpecimen

# Avoid circular imports:
# - prompts.builder imports from here
if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

RATIO_SUM_TOLERANCE = 0.01  # Allow ±0.01 deviation from 1.0


# =============================================================================
# Helper Functions
# =============================================================================


def _get_required_critique(session: Session, critique_id: UUID) -> Critique:
    """Fetch critique from DB or raise ToolError."""
    if (critique := session.get(Critique, critique_id)) is None:
        raise ToolError(f"Critique {critique_id} not found in database")
    return critique


# =============================================================================
# Grader Run Models
# =============================================================================


class GraderInput(BaseModel):
    """Input for a grader run (critique + specimen → metrics)."""

    specimen_slug: SpecimenSlug = Field(description="Specimen being graded")
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
    """Validation context: allowed IDs and required files for grading.

    Context key: "grade_validation_context"
    """

    allowed_tp_ids: set[TruePositiveID]
    allowed_fp_ids: set[FalsePositiveID]
    allowed_input_ids: set[InputIssueID]
    tp_files: set[SpecimenRelativePath]  # Files with canonical TPs (need recall)
    critique_files: set[SpecimenRelativePath]  # Files with critique issues (need ratios)

    @classmethod
    def from_specimen_and_critique(
        cls, specimen: HydratedSpecimen, critique: CriticSubmitPayload
    ) -> GradeValidationContext:
        """Build validation context from specimen and critique."""
        # Collect files from canonical TPs and critique issues
        # Use specimen's convenience properties (delegates to .record)
        tp_files = {
            f for issue_rec in specimen.issues.values() for instance in issue_rec.instances for f in instance.files
        }

        critique_files = {f for issue in critique.issues for occ in issue.occurrences for f in occ.files}

        return cls(
            allowed_tp_ids={TruePositiveID(id) for id in specimen.issues},
            allowed_fp_ids={FalsePositiveID(id) for id in specimen.false_positives},
            allowed_input_ids={InputIssueID(issue.id) for issue in critique.issues},
            tp_files=tp_files,
            critique_files=critique_files,
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
    summary: Rationale = Field(
        description="Markdown summary with high-level observations. Use for cross-cutting patterns, weighting rationale (if non-obvious), or specimen-level notes. Do NOT repeat per-issue details already in rationale fields—assume reader sees entire object."
    )

    # Per-file metrics (split by what needs to be tracked)
    per_file_recall: dict[SpecimenRelativePath, float] = Field(
        ...,
        description="Recall [0,1] for EVERY file with canonical TPs. Keys = file paths. Value = fraction of canonical TPs in this file that were covered, weighted by importance/severity.",
    )

    per_file_ratios: dict[SpecimenRelativePath, ReportedIssueRatios] = Field(
        ...,
        description="Ratios {tp,fp,unlabeled} for EVERY file with critique issues. Keys = file paths. Value = ratios for reported issues touching this file, weighted, must sum to ~1.0.",
    )

    model_config = ConfigDict(extra="forbid")

    def _get_validation_context(self, info: ValidationInfo) -> GradeValidationContext | None:
        """Get validation context if available and correct type."""
        if info.context is None:
            return None
        ctx = info.context.get("grade_validation_context")
        if ctx is None or not isinstance(ctx, GradeValidationContext):
            return None
        return cast(GradeValidationContext, ctx)

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

    @model_validator(mode="after")
    def validate_per_file_metrics_complete(self, info: ValidationInfo) -> GradeSubmitInput:
        """Validate per-file metrics cover exactly the required files."""
        if (ctx := self._get_validation_context(info)) is None:
            return self

        # Check per_file_recall keys match tp_files
        provided_recall = set(self.per_file_recall.keys())
        missing_recall = ctx.tp_files - provided_recall
        if missing_recall:
            raise ValueError(
                f"Missing per_file_recall for: {sorted(str(f) for f in missing_recall)}. "
                f"Must provide recall for all files with canonical TPs."
            )

        extra_recall = provided_recall - ctx.tp_files
        if extra_recall:
            raise ValueError(
                f"Unexpected per_file_recall for: {sorted(str(f) for f in extra_recall)}. "
                f"Only provide recall for files with canonical TPs."
            )

        # Check per_file_ratios keys match critique_files
        provided_ratios = set(self.per_file_ratios.keys())
        missing_ratios = ctx.critique_files - provided_ratios
        if missing_ratios:
            raise ValueError(
                f"Missing per_file_ratios for: {sorted(str(f) for f in missing_ratios)}. "
                f"Must provide ratios for all files with critique issues."
            )

        extra_ratios = provided_ratios - ctx.critique_files
        if extra_ratios:
            raise ValueError(
                f"Unexpected per_file_ratios for: {sorted(str(f) for f in extra_ratios)}. "
                f"Only provide ratios for files with critique issues."
            )

        return self


class GradeSubmitState:
    """Container for submitted GradeSubmitInput."""

    result: GradeSubmitInput | None = None


@dataclass(frozen=True)
class GradeInputs:
    """Grading context: specimen and critique."""

    specimen: HydratedSpecimen
    critique: CriticSubmitPayload


def build_grader_submit_tools(mcp: NotifyingFastMCP, state: GradeSubmitState, *, inputs: GradeInputs) -> None:
    """Register grader submit tool with validation context."""
    # Build validation context using factory method (INPUT BOUNDARY - typed IDs created here)
    context = GradeValidationContext.from_specimen_and_critique(inputs.specimen, inputs.critique)

    @mcp.flat_model()
    async def submit_result(payload: GradeSubmitInput) -> SimpleOk:
        """Submit the final grading result."""
        # Re-validate with context to trigger all validators
        state.result = GradeSubmitInput.model_validate(
            payload.model_dump(), context={"grade_validation_context": context}
        )
        return SimpleOk(ok=True)


def make_grader_submit_server(
    state: GradeSubmitState, *, name: str = "grader_submit", inputs: GradeInputs
) -> NotifyingFastMCP:
    """Create MCP server with submit_result tool."""

    mcp = NotifyingFastMCP(name)
    build_grader_submit_tools(mcp, state, inputs=inputs)

    return mcp


@render_to_rich.register
def _render_grade_submit_input(obj: GradeSubmitInput):
    """Rich renderer: coverage tables and summary."""
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
        coverage_recall = (
            sum(min(1.0, cov.recall_credit) for cov in obj.canonical_tp_coverage.values()) / total_canonical_tps
        )

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

    return Panel(
        bits[0] if len(bits) == 1 else Group(*bits),
        title="[bold blue]Grader Submission[/bold blue]",
        border_style="blue",
        padding=(1, 2),
    )


# =============================================================================
# Grader Run Function
# =============================================================================


async def run_grader(
    *,
    input_data: GraderInput,
    client: OpenAIModelProto,
    hydrated_specimen: HydratedSpecimen,
    extra_handlers: tuple[BaseHandler, ...] = (),
    verbose: bool = False,
) -> tuple[GraderOutput, UUID]:
    """Run grader agent: evaluate critique against ground truth, persist to DB."""
    # Import at function level to avoid circular dependency (prompts.builder → grader)
    from adgn.props.prompts.builder import build_grade_from_json_prompt

    # Generate unique IDs for this run
    run_id = uuid4()
    transcript_id = uuid4()

    # Phase 1: Write initial run and fetch critique (BEFORE agent runs)
    with get_session() as session:
        db_run = DBGraderRun(
            id=run_id,
            transcript_id=transcript_id,
            specimen_slug=input_data.specimen_slug,
            model=client.model,
            critique_id=input_data.critique_id,
            prompt_optimization_run_id=input_data.prompt_optimization_run_id,
            output=None,  # Will be set in Phase 2
        )
        session.add(db_run)
        session.commit()
        logger.info(
            f"Created initial grader run in DB: {run_id=}, {transcript_id=}, specimen_slug={input_data.specimen_slug}"
        )

        # Fetch critique from database
        critique = CriticSubmitPayload.model_validate(_get_required_critique(session, input_data.critique_id).payload)

    # Use specimen's canonical issues and false positives (via convenience properties)
    canonical_typed = hydrated_specimen.record.canonical_issues
    fp_typed = hydrated_specimen.record.known_false_positives

    # Convert critique issues to CritiqueInputIssue
    critique_typed = [
        CritiqueInputIssue(id=InputIssueID(issue.id), rationale=issue.rationale, occurrences=issue.occurrences)
        for issue in critique.issues
    ]

    # Build grader inputs and state
    grader_state = GradeSubmitState()
    inputs = GradeInputs(specimen=hydrated_specimen, critique=critique)

    submit_tool_name = build_mcp_function(GRADER_SUBMIT_SERVER_NAME, "submit_result")

    wiring = properties_docker_spec(hydrated_specimen.content_root, mount_properties=True, ephemeral=False)
    prompt = build_grade_from_json_prompt(
        canonical_issues=canonical_typed,
        critique_issues=critique_typed,
        known_fps=fp_typed,
        submit_tool_name=submit_tool_name,
        wiring=wiring,
    )

    # Set up compositor and servers
    comp = Compositor("compositor")
    runtime_server = await wiring.attach(comp)
    grader_submit_server = NotifyingFastMCP(
        GRADER_SUBMIT_SERVER_NAME, instructions="Final grader submission for critique evaluation"
    )
    build_grader_submit_tools(grader_submit_server, grader_state, inputs=inputs)
    await comp.mount_inproc(GRADER_SUBMIT_SERVER_NAME, grader_submit_server)

    # Set up handlers
    servers = {wiring.server_name: runtime_server, GRADER_SUBMIT_SERVER_NAME: grader_submit_server}

    handlers: list = [
        AbortIf(should_abort=lambda: grader_state.result is not None),
        *build_props_handlers(
            transcript_id=transcript_id,
            verbose_prefix=f"[GRADER {input_data.specimen_slug}] " if verbose else None,
            servers=servers,
        ),
        *extra_handlers,
    ]

    # Run grader agent
    # TODO: Consider adding BootstrapInspectHandler (like critic) to inject container.info resource read
    #       for better agent context about runtime environment
    async with Client(comp) as mcp_client:
        await mount_standard_inproc_servers(compositor=comp)
        agent = await MiniCodex.create(
            mcp_client=mcp_client,
            system="You are a strict grader. Return only metrics via submit_result.",
            client=client,
            handlers=handlers,
            parallel_tool_calls=True,
            reasoning_summary=ReasoningSummary.detailed,
            tool_policy=RequireAnyTool(),
        )
        await agent.run(prompt)

    if grader_state.result is None:
        raise ToolError("Grader did not submit result")

    output = GraderOutput(grade=grader_state.result)

    # Phase 2: Update run with output
    with get_session() as session:
        found_run = session.get(DBGraderRun, run_id)
        assert found_run is not None, f"Grader run {run_id} not found in database"
        found_run.output = output.model_dump(mode="json")
        session.commit()
        logger.info(f"Updated grader run in DB: {transcript_id=}, specimen_slug={input_data.specimen_slug}")

    return (output, run_id)


async def grade_critique_by_id(critique_id: UUID, client: OpenAIModelProto, verbose: bool = False) -> UUID:
    """Grade critique by ID, return grader_run_id."""
    # Import at function level to avoid circular dependency
    from adgn.props.specimens.registry import SpecimenRegistry

    # Fetch specimen_slug from critique
    with get_session() as session:
        specimen_slug = _get_required_critique(session, critique_id).specimen_slug

    # Create grader input
    grader_input = GraderInput(specimen_slug=specimen_slug, critique_id=critique_id)

    # Load and hydrate specimen once, then execute
    registry = SpecimenRegistry.from_package_resources()
    async with registry.load_and_hydrate(specimen_slug) as hydrated:
        # Execute grader run
        _grader_output, grader_run_id = await run_grader(
            input_data=grader_input, client=client, hydrated_specimen=hydrated, verbose=verbose
        )

        return grader_run_id
