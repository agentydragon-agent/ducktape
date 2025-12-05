"""Grader MCP server and GradeSubmitPayload models.

Defines structured output used by critique grader:
(specimen canonical issues + input critique JSON → metrics + markdown summary)
AND a tiny FastMCP server that accepts exactly one submission per run via
submit_result.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from uuid import UUID, uuid4

from fastmcp.client import Client
from fastmcp.exceptions import ToolError
from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from sqlalchemy.orm import Session

from adgn.agent.agent import MiniCodex
from adgn.agent.handler import AbortIf, BaseHandler
from adgn.agent.loop_control import RequireAnyTool
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
from adgn.props.critic.models import CriticSubmitPayload
from adgn.props.db import get_session
from adgn.props.db.models import Critique, GraderRun as DBGraderRun, Snapshot
from adgn.props.docker_env import properties_docker_spec
from adgn.props.grader.models import (
    CritiqueInputIssue,
    FalsePositiveID,
    GraderInput,
    GraderOutput,
    GradeSubmitInput,
    GradeValidationContext,
    KnownFalsePositive,
    TruePositiveID,
    TruePositiveIssue,
)
from adgn.props.ids import InputIssueID, SnapshotSlug
from adgn.props.prompts.builder import build_grade_from_json_prompt
from adgn.props.rationale import Rationale
from adgn.props.snapshot_hydrated import HydratedSnapshot
from adgn.props.snapshot_hydrator import SnapshotHydrator

logger = logging.getLogger(__name__)


# =============================================================================
# Helper Functions
# =============================================================================


def _tp_from_orm(orm_tp) -> TruePositiveIssue:
    """Convert ORM TruePositive to grader representation (module-private)."""
    return TruePositiveIssue(
        id=TruePositiveID(orm_tp.tp_id), rationale=Rationale(orm_tp.rationale), occurrences=orm_tp.occurrences
    )


def _fp_from_orm(orm_fp) -> KnownFalsePositive:
    """Convert ORM FalsePositive to grader representation (module-private)."""
    return KnownFalsePositive(
        id=FalsePositiveID(orm_fp.fp_id), rationale=Rationale(orm_fp.rationale), occurrences=orm_fp.occurrences
    )


def _get_required_critique(session: Session, critique_id: UUID) -> Critique:
    """Fetch critique from DB or raise ToolError."""
    if (critique := session.get(Critique, critique_id)) is None:
        raise ToolError(f"Critique {critique_id} not found in database")
    return critique


class GradeSubmitState:
    """Container for submitted GradeSubmitInput."""

    result: GradeSubmitInput | None = None


@dataclass(frozen=True)
class GradeInputs:
    """Grading context: snapshot slug and critique."""

    snapshot_slug: SnapshotSlug
    critique: CriticSubmitPayload
    reviewed_files: set[Path] | None = None  # Files reviewed by critic (for scope filtering)


def build_grader_submit_tools(mcp: NotifyingFastMCP, state: GradeSubmitState, *, inputs: GradeInputs) -> None:
    """Register grader submit tool with validation context."""
    # Load ORM snapshot from database for ground truth issues
    with get_session() as session:
        snapshot_orm = session.query(Snapshot).filter_by(slug=inputs.snapshot_slug).one()

        # Build validation context using factory method (INPUT BOUNDARY - typed IDs created here)
        # Pass reviewed_files for scope filtering if available
        context = GradeValidationContext.from_specimen_and_critique(
            snapshot_orm, inputs.critique, reviewed_files=inputs.reviewed_files
        )

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
        coverage_recall = sum(cov.recall_credit for cov in obj.canonical_tp_coverage.values()) / total_canonical_tps

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
    hydrated_specimen: HydratedSnapshot,
    canonical_tps: list[TruePositiveIssue],
    canonical_fps: list[KnownFalsePositive],
    extra_handlers: tuple[BaseHandler, ...] = (),
    verbose: bool = False,
) -> tuple[GraderOutput, UUID]:
    """Run grader agent: evaluate critique against ground truth, persist to DB.

    Args:
        input_data: Grader input with snapshot_slug and critique_id
        client: OpenAI client
        hydrated_specimen: Hydrated snapshot (only content_root used, not record)
        canonical_tps: Canonical true positives (from DB or registry)
        canonical_fps: Known false positives (from DB or registry)
        extra_handlers: Additional handlers
        verbose: Enable verbose output

    Returns:
        Tuple of (GraderOutput, grader_run_id)
    """
    # Generate unique IDs for this run
    run_id = uuid4()
    transcript_id = uuid4()

    # Phase 1: Write initial run and fetch critique (BEFORE agent runs)
    with get_session() as session:
        session.add(
            DBGraderRun(
                id=run_id,
                transcript_id=transcript_id,
                snapshot_slug=input_data.snapshot_slug,
                model=client.model,
                critique_id=input_data.critique_id,
                prompt_optimization_run_id=input_data.prompt_optimization_run_id,
                output=None,  # Will be set in Phase 2
            )
        )
        session.commit()
        logger.info(
            f"Created initial grader run in DB: {run_id=}, {transcript_id=}, snapshot_slug={input_data.snapshot_slug}"
        )

        # Fetch critique from database
        critique_orm = _get_required_critique(session, input_data.critique_id)
        critique = CriticSubmitPayload.model_validate(critique_orm.payload)

        # Extract reviewed files from critic run while still in session (for scope filtering)
        # TODO: Clean up path propagation - reviewed_files is extracted here, passed through
        # GradeInputs, then used in both build_grader_submit_tools (for validation) and
        # grade_critique_by_id (for prompt filtering). Consider refactoring to single source
        # or making the critique → files relationship more explicit.
        from adgn.props.grader.models import FILTER_TPS_BY_CRITIC_SCOPE

        reviewed_files: set[Path] | None = None
        if FILTER_TPS_BY_CRITIC_SCOPE and critique_orm.critic_run:
            reviewed_files = {Path(f) for f in critique_orm.critic_run.files}

    # Convert critique issues to CritiqueInputIssue
    critique_typed = [
        CritiqueInputIssue(id=InputIssueID(issue.id), rationale=issue.rationale, occurrences=issue.occurrences)
        for issue in critique.issues
    ]

    # Build grader inputs and state
    grader_state = GradeSubmitState()
    inputs = GradeInputs(snapshot_slug=input_data.snapshot_slug, critique=critique, reviewed_files=reviewed_files)

    wiring = properties_docker_spec(hydrated_specimen.content_root, mount_properties=True, ephemeral=False)
    prompt = build_grade_from_json_prompt(
        true_positive_issues=canonical_tps,
        critique_issues=critique_typed,
        known_fps=canonical_fps,
        submit_tool_name=build_mcp_function(GRADER_SUBMIT_SERVER_NAME, "submit_result"),
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

    # Run grader agent
    # TODO: Consider adding BootstrapInspectHandler (like critic) to inject container.info resource read
    #       for better agent context about runtime environment
    async with Client(comp) as mcp_client:
        await mount_standard_inproc_servers(compositor=comp)
        agent = await MiniCodex.create(
            mcp_client=mcp_client,
            system="You are a strict grader. Return only metrics via submit_result.",
            client=client,
            handlers=[
                AbortIf(should_abort=lambda: grader_state.result is not None),
                *build_props_handlers(
                    transcript_id=transcript_id,
                    verbose_prefix=f"[GRADER {str(transcript_id)[:8]} {input_data.snapshot_slug}] "
                    if verbose
                    else None,
                    servers=servers,
                ),
                *extra_handlers,
            ],
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
        found_run.output = output
        session.commit()
        logger.info(f"Updated grader run in DB: {transcript_id=}, snapshot_slug={input_data.snapshot_slug}")

    return (output, run_id)


async def grade_critique_by_id(
    session: Session, critique_id: UUID, client: OpenAIModelProto, verbose: bool = False
) -> UUID:
    """Grade critique by ID, return grader_run_id.

    Args:
        session: Database session (caller manages transaction)
        critique_id: ID of critique to grade
        client: OpenAI client
        registry: Snapshot registry (still required for source hydration)
        verbose: Enable verbose output

    Returns:
        Grader run ID
    """
    # Fetch snapshot from critique
    critique = _get_required_critique(session, critique_id)
    snapshot_slug = critique.snapshot_slug

    # Load snapshot and issues from database (no jsonnet!)
    snapshot = session.query(Snapshot).filter_by(slug=snapshot_slug).one()

    # Convert ORM → Pydantic wrappers for grader prompt
    canonical_tps = [_tp_from_orm(tp) for tp in snapshot.true_positives]
    canonical_fps = [_fp_from_orm(fp) for fp in snapshot.false_positives]

    # Filter TPs/FPs by critic scope if enabled
    from adgn.props.grader.models import FILTER_TPS_BY_CRITIC_SCOPE

    if FILTER_TPS_BY_CRITIC_SCOPE and critique.critic_run:
        from adgn.props.models.true_positive import should_catch_occurrence, should_show_fp_occurrence

        reviewed_files = {Path(f) for f in critique.critic_run.files}

        # Only include TPs where at least one occurrence is catchable from reviewed files
        canonical_tps = [
            tp for tp in canonical_tps if any(should_catch_occurrence(occ, reviewed_files) for occ in tp.occurrences)
        ]

        # Only include FPs where at least one occurrence is relevant to reviewed files
        canonical_fps = [
            fp for fp in canonical_fps if any(should_show_fp_occurrence(occ, reviewed_files) for occ in fp.occurrences)
        ]

    # Create grader input
    grader_input = GraderInput(snapshot_slug=snapshot_slug, critique_id=critique_id)

    # Hydrate source code only (not issues - already loaded from DB)
    hydrator = SnapshotHydrator.from_package_resources()
    async with hydrator.hydrate(snapshot_slug) as hydrated:
        # Execute grader run with explicit canonical issues
        _grader_output, grader_run_id = await run_grader(
            input_data=grader_input,
            client=client,
            hydrated_specimen=hydrated,
            canonical_tps=canonical_tps,
            canonical_fps=canonical_fps,
            verbose=verbose,
        )

        return grader_run_id
