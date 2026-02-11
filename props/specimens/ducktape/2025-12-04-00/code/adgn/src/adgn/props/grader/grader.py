"""Grader MCP server and GradeSubmitPayload models.

Defines structured output used by critique grader:
(specimen canonical issues + input critique JSON → metrics + markdown summary)
AND a tiny FastMCP server that accepts exactly one submission per run via
submit_result.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from fastmcp.client import Client
from fastmcp.exceptions import ToolError
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
from adgn.props.critic.models import CriticSubmitPayload
from adgn.props.db import get_session
from adgn.props.db.models import Critique, GraderRun as DBGraderRun
from adgn.props.docker_env import properties_docker_spec
from adgn.props.grader.models import (
    CritiqueInputIssue,
    GraderInput,
    GraderOutput,
    GradeSubmitInput,
    GradeValidationContext,
)
from adgn.props.ids import InputIssueID
from adgn.props.prompts.builder import build_grade_from_json_prompt
from adgn.props.snapshot_hydrated import HydratedSnapshot
from adgn.props.snapshot_registry import SnapshotRegistry

# Avoid circular imports:
# - prompts.builder imports from here
if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# =============================================================================
# Helper Functions
# =============================================================================


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
    """Grading context: specimen and critique."""

    specimen: HydratedSnapshot
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
    hydrated_specimen: HydratedSnapshot,
    extra_handlers: tuple[BaseHandler, ...] = (),
    verbose: bool = False,
) -> tuple[GraderOutput, UUID]:
    """Run grader agent: evaluate critique against ground truth, persist to DB."""
    # Generate unique IDs for this run
    run_id = uuid4()
    transcript_id = uuid4()

    # Phase 1: Write initial run and fetch critique (BEFORE agent runs)
    with get_session() as session:
        db_run = DBGraderRun(
            id=run_id,
            transcript_id=transcript_id,
            snapshot_slug=input_data.snapshot_slug,
            model=client.model,
            critique_id=input_data.critique_id,
            prompt_optimization_run_id=input_data.prompt_optimization_run_id,
            output=None,  # Will be set in Phase 2
        )
        session.add(db_run)
        session.commit()
        logger.info(
            f"Created initial grader run in DB: {run_id=}, {transcript_id=}, snapshot_slug={input_data.snapshot_slug}"
        )

        # Fetch critique from database
        critique = CriticSubmitPayload.model_validate(_get_required_critique(session, input_data.critique_id).payload)

    # Use specimen's canonical issues and false positives (via convenience properties)
    canonical_typed = hydrated_specimen.record.true_positive_issues
    fp_typed = hydrated_specimen.record.known_false_positives_list

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
        true_positive_issues=canonical_typed,
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
            verbose_prefix=f"[GRADER {input_data.snapshot_slug}] " if verbose else None,
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
        logger.info(f"Updated grader run in DB: {transcript_id=}, snapshot_slug={input_data.snapshot_slug}")

    return (output, run_id)


async def grade_critique_by_id(
    session: Session, critique_id: UUID, client: OpenAIModelProto, registry: SnapshotRegistry, verbose: bool = False
) -> UUID:
    """Grade critique by ID, return grader_run_id.

    Args:
        session: Database session (caller manages transaction)
        critique_id: ID of critique to grade
        client: OpenAI client
        registry: Snapshot registry (required - caller must provide)
        verbose: Enable verbose output

    Returns:
        Grader run ID
    """
    # Fetch snapshot_slug from critique
    snapshot_slug = _get_required_critique(session, critique_id).snapshot_slug

    # Create grader input
    grader_input = GraderInput(snapshot_slug=snapshot_slug, critique_id=critique_id)

    # Load and hydrate specimen once, then execute
    async with registry.load_and_hydrate(snapshot_slug) as hydrated:
        # Execute grader run
        _grader_output, grader_run_id = await run_grader(
            input_data=grader_input, client=client, hydrated_specimen=hydrated, verbose=verbose
        )

        return grader_run_id
