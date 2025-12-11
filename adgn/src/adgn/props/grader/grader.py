"""Grader MCP server and GradeSubmitPayload models.

Defines structured output used by critique grader:
(specimen canonical issues + input critique JSON → metrics + markdown summary)
AND a tiny FastMCP server that accepts exactly one submission per run via
submit_result.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import aiodocker
from fastmcp import FastMCP
from fastmcp.client import Client
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AuthProvider, StaticTokenVerifier
from fastmcp.tools import FunctionTool
from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from adgn.mcp._shared.mounted import Mounted

from adgn.agent.agent import Agent
from adgn.agent.handler import AbortIf, BaseHandler
from adgn.agent.loop_control import RequireAnyTool
from adgn.agent.turn_limit import MaxTurnsHandler
from adgn.llm.rendering.rich_renderers import render_to_rich
from adgn.mcp._shared.types import SimpleOk
from adgn.mcp.enhanced import EnhancedFastMCP
from adgn.openai_utils.model import OpenAIModelProto, SystemMessage, UserMessage
from adgn.openai_utils.types import ReasoningSummary
from adgn.props.agent_setup import build_props_handlers
from adgn.props.cli.common_options import DEFAULT_MAX_LINES
from adgn.props.db import get_session
from adgn.props.db.config import get_production_config
from adgn.props.db.models import (
    CanonicalIssuesSnapshot,
    Critique,
    DBCriticSubmitPayload,
    GraderRun as DBGraderRun,
    Snapshot,
)
from adgn.props.docker_env import PropertiesDockerCompositor
from adgn.props.grader.exceptions import GraderDidNotSubmitError
from adgn.props.grader.models import (
    CritiqueInputIssue,
    FalsePositiveID,
    GraderInput,
    GradeSubmitInput,
    GradeValidationContext,
    KnownFalsePositive,
    TruePositiveID,
    TruePositiveIssue,
)
from adgn.props.grader.persistence import fp_to_db, grade_submit_input_to_db, tp_to_db
from adgn.props.http_compositor import PropertiesDockerCompositorHTTP
from adgn.props.hydration import HydratedSnapshot, SnapshotHydrator
from adgn.props.ids import InputIssueID, SnapshotSlug
from adgn.props.models.true_positive import (
    FileOccurrence,
    LineRange,
    Occurrence,
    should_catch_occurrence,
    should_show_fp_occurrence,
)
from adgn.props.prompts.builder import build_grade_from_json_prompt
from adgn.props.prompts.util import MCP_HTTP_CONNECTION_INSTRUCTIONS
from adgn.props.rationale import Rationale

logger = logging.getLogger(__name__)

# Toggle for MCP HTTP transport (Phase 1: parallel with compositor)
# Set via environment variable: ADGN_USE_MCP_HTTP=1
# When enabled:
#   - grader_submit server launches via HTTP transport
#   - MCP_SERVER_URL and MCP_SERVER_TOKEN are injected into container environment
#   - Bootstrap inspects the MCP server to show its tools/resources/instructions
#   - Container uses custom network config to allow host access but block internet
# When disabled:
#   - grader_submit server is mounted in-proc (no HTTP server)
#   - No MCP environment variables are set in the container
#   - No bootstrap inspection runs
#   - Container uses network_mode="none" (full isolation)
USE_MCP_HTTP = os.getenv("ADGN_USE_MCP_HTTP", "").lower() in ("1", "true", "yes")


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
    critique: DBCriticSubmitPayload  # DB persistence model (not MCP I/O model)
    reviewed_files: set[Path] | None = None  # Files reviewed by critic (for scope filtering)


GRADER_SUBMIT_INSTRUCTIONS = """\
Grader submission server for critique evaluation.

Use submit_result to submit the final grading comparing critique against ground truth.
"""

GRADER_COMMON_INSTRUCTIONS = """\
You will exclusively act by calling tools. Do not send any text messages at any point. When you successfully submit your result, this conversation will abort automatically. As long as this conversation continues, you have not yet correctly sent a submission to the MCP server.

If your submission is rejected or returns an error from the grader_submit server, read the error message carefully, fix the issues in your payload (such as incorrect field types, missing required fields, or validation errors), and resubmit the corrected result. Keep retrying until the submission succeeds.\
"""


class GraderSubmitServer(EnhancedFastMCP):
    """Grader submit MCP server with typed tool access.

    Provides submit_result tool for grading workflow.
    """

    # Tool name constant (for test infrastructure only)
    SUBMIT_RESULT_TOOL_NAME = "submit_result"

    # Tool reference (assigned in __init__)
    submit_result_tool: FunctionTool

    def __init__(self, state: GradeSubmitState, inputs: GradeInputs, auth: AuthProvider | None = None):
        """Create grader submit server with state container and validation context.

        Args:
            state: State container for submitted result.
            inputs: Grading context (snapshot slug and critique).
            auth: Auth provider for HTTP mode (None for inproc).
        """
        super().__init__("Grader Submit Server", instructions=GRADER_SUBMIT_INSTRUCTIONS, auth=auth)

        # Load ORM snapshot from database for ground truth issues
        with get_session() as session:
            snapshot_orm = session.query(Snapshot).filter_by(slug=inputs.snapshot_slug).one()

            # Build validation context using factory method (INPUT BOUNDARY - typed IDs created here)
            # Pass reviewed_files for scope filtering if available
            context = GradeValidationContext.from_specimen_and_critique(
                snapshot_orm, inputs.critique, reviewed_files=inputs.reviewed_files
            )

        # Register tool - name derived from function name
        async def submit_result(payload: GradeSubmitInput) -> SimpleOk:
            """Submit the final grading result."""
            # Re-validate with context to trigger all validators
            state.result = GradeSubmitInput.model_validate(
                payload.model_dump(), context={"grade_validation_context": context}
            )
            return SimpleOk(ok=True)

        self.submit_result_tool = self.flat_model()(submit_result)


@render_to_rich.register
def _render_grade_submit_input(obj: GradeSubmitInput):
    """Rich renderer: coverage tables and summary."""
    bits: list[RenderableType] = []

    # Compute derived metrics for display
    total_canonical_tps = len(obj.canonical_tp_coverage)
    total_canonical_fps = len(obj.canonical_fp_coverage)
    covered_tps = sum(1 for entry in obj.canonical_tp_coverage if entry.coverage.covered_by)
    matched_fps = sum(1 for entry in obj.canonical_fp_coverage if entry.coverage.covered_by)
    uncovered_tps = total_canonical_tps - covered_tps
    novel_count = len(obj.novel_critique_issues)

    # Main metrics table
    metrics_tbl = Table(title="Grading Metrics", show_lines=False, expand=True)
    metrics_tbl.add_column("Metric", style="cyan", no_wrap=True)
    metrics_tbl.add_column("Value", style="magenta")
    metrics_tbl.add_column("Description", style="dim")

    metrics_tbl.add_row("Recall", f"{obj.recall:.1%}", "Weighted fraction of canonicals covered")
    if obj.reported_issue_ratios is not None:
        metrics_tbl.add_row("TP ratio", f"{obj.reported_issue_ratios.tp:.1%}", "Reported issues matching canonicals")
        metrics_tbl.add_row("FP ratio", f"{obj.reported_issue_ratios.fp:.1%}", "Reported issues matching known FPs")
        metrics_tbl.add_row("Unlabeled ratio", f"{obj.reported_issue_ratios.unlabeled:.1%}", "Novel/unknown issues")
    else:
        metrics_tbl.add_row("Issue ratios", "N/A", "Empty critique (no issues reported)")
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


class GraderCompositor(PropertiesDockerCompositor):
    """Compositor with grader servers pre-mounted (inproc mode only).

    Inherits from PropertiesDockerCompositor, which provides:
    - runtime: Docker exec server (mounted by parent class)

    Adds:
    - grader_submit: Grader submission server

    Note: This handles only inproc mode. HTTP mode is handled separately.
    """

    # Mount prefix constant (for test infrastructure only)
    SUBMIT_PREFIX = "grader_submit"

    # Mounted server attributes (runtime inherited, grader_submit added here)
    grader_submit: Mounted[GraderSubmitServer]

    def __init__(
        self,
        workspace_root: Path,
        docker_client: aiodocker.Docker,
        grader_state: GradeSubmitState,
        inputs: GradeInputs,
        **kwargs,
    ):
        """Create compositor with grader dependencies.

        Args:
            workspace_root: Path to workspace directory to mount in container.
            docker_client: Async Docker client (managed by caller).
            grader_state: Grader submit state container.
            inputs: Grading context (snapshot slug and critique).
            **kwargs: Additional arguments passed to PropertiesDockerCompositor
                (mount_properties, db_conn, extra_binds, workspace_mode, network_mode, extra_env, ephemeral)
        """
        super().__init__(workspace_root, docker_client, **kwargs)
        self._grader_state = grader_state
        self._inputs = inputs

    async def __aenter__(self):
        """Start compositor and mount servers."""
        # Start parent compositor (mounts resources, compositor_meta, runtime)
        await super().__aenter__()

        # Mount grader submit server
        self.grader_submit = await self.mount_inproc(
            "grader_submit", GraderSubmitServer(self._grader_state, self._inputs), pinned=True
        )

        return self


# =============================================================================
# Bootstrap Helpers
# =============================================================================

# Bootstrap function disabled - example code is embedded in system prompt instead
# def make_grader_http_bootstrap_calls(
#     compositor, builder: TypedBootstrapBuilder
# ) -> list[FunctionCallItem]:
#     """Build bootstrap calls for grader in HTTP mode: inspect MCP server with auth.
#
#     Args:
#         wiring: Docker container wiring (provides server_name)
#         builder: Bootstrap builder with call ID generation
#
#     Returns:
#         List of bootstrap function calls that inspect the MCP server
#     """
#     from importlib.resources import files
#
#     # Load MCP inspection script from package resource
#     grader_pkg = files("adgn.props.grader")
#     inspect_script = (grader_pkg / "mcp_inspect.py").read_text()
#
#     return [
#         # First verify environment variables are set
#         docker_exec_call(
#             builder,
#             server=wiring.server_name,
#             cmd=["sh", "-c", "echo 'MCP_SERVER_URL='$MCP_SERVER_URL; echo 'MCP_SERVER_TOKEN='$MCP_SERVER_TOKEN"],
#             timeout_ms=5_000,
#         ),
#         # Then run the inspection script
#         docker_exec_call(builder, server=wiring.server_name, cmd=["python3", "-c", inspect_script], timeout_ms=15_000),
#     ]


# =============================================================================
# Agent Execution
# =============================================================================


async def _run_grader_agent(
    *,
    grader_state: GradeSubmitState,
    inputs: GradeInputs,
    workspace_root: Path,
    docker_client: aiodocker.Docker,
    canonical_tps: list[TruePositiveIssue],
    critique_typed: list[CritiqueInputIssue],
    canonical_fps: list[KnownFalsePositive],
    client: OpenAIModelProto,
    transcript_id: UUID,
    snapshot_split: str,
    input_data: GraderInput,
    verbose: bool,
    extra_handlers: tuple[BaseHandler, ...],
    http_mode: bool = False,
    max_lines: int = DEFAULT_MAX_LINES,
    max_turns: int | None = None,
) -> None:
    """Run the grader agent.

    Args:
        http_mode: If True, grader_submit is exposed via HTTP (managed by PropertiesDockerCompositorHTTP).
            If False, grader_submit is mounted in compositor.
        canonical_tps: True positive issues from specimen
        critique_typed: Issues from the critique being graded
        canonical_fps: Known false positives from specimen
    """
    # Choose compositor based on http_mode
    # HTTP mode: use PropertiesDockerCompositorHTTP (manages both HTTP server and container)
    #            Network: PROPS_NETWORK_NAME, workspace: rw, ephemeral: False, db_conn: required
    # Inproc mode: use GraderCompositor (runtime + grader_submit mounted in-proc)
    #              Network: "none" (isolated, no network access needed)
    comp_ctx: PropertiesDockerCompositor
    if http_mode:
        # Server factory for HTTP compositor
        def server_factory(token: str) -> EnhancedFastMCP:
            auth = StaticTokenVerifier(tokens={token: {"client_id": "grader-agent", "scopes": []}})
            return GraderSubmitServer(grader_state, inputs, auth)

        db_config = get_production_config()
        comp_ctx = PropertiesDockerCompositorHTTP(
            workspace_root,
            docker_client,
            server_factory=server_factory,
            db_conn=db_config.agent_for_container,
            mount_properties=False,
        )
    else:
        comp_ctx = GraderCompositor(
            workspace_root=workspace_root,
            docker_client=docker_client,
            grader_state=grader_state,
            inputs=inputs,
            mount_properties=False,
            ephemeral=False,
            # network_mode defaults to "none" (isolated)
        )

    async with comp_ctx as handle:
        # Build servers dict for agent
        # HTTP mode: only runtime (grader_submit is external)
        # Inproc mode: runtime + grader_submit
        if http_mode:
            servers: dict[str, FastMCP | None] = {handle.runtime.prefix: handle.runtime.server}
        else:
            # Type narrowing: handle is GraderCompositor in else branch
            assert isinstance(handle, GraderCompositor)
            servers = {
                handle.runtime.prefix: handle.runtime.server,
                handle.grader_submit.prefix: handle.grader_submit.server,
            }

        # Build prompt now that we have access to servers
        # Tool name differs based on mode:
        # - HTTP mode: direct connection to grader server, use bare tool name from server instance
        # - In-proc mode: via compositor, use Mounted.tool_name() helper (adds prefix)
        if http_mode:
            # Instantiate server to get tool name (doesn't need to be mounted)
            temp_server = GraderSubmitServer(grader_state, inputs)
            submit_tool_name = temp_server.submit_result_tool.name
        else:
            # Type narrowing: handle is GraderCompositor in else branch
            assert isinstance(handle, GraderCompositor)
            submit_tool_name = handle.grader_submit.tool_name(handle.grader_submit.server.submit_result_tool)

        prompt = build_grade_from_json_prompt(
            true_positive_issues=canonical_tps,
            critique_issues=critique_typed,
            known_fps=canonical_fps,
            submit_tool_name=submit_tool_name,
            compositor=handle,
        )

        # Note: resources and compositor_meta are auto-mounted by base Compositor
        async with Client(handle) as mcp_client:
            # Build system prompt with MCP HTTP instructions if in http_mode
            if http_mode:
                system = f"""You are a strict grader evaluating a code critique.

Grade the critique, then submit your result by invoking the MCP server's submit_result tool.

You do not have direct access to invoke the server's tools - the MCP server is networked to the container that docker_exec runs commands in. To interact with the server (and to submit your work using its submit_result tool), use docker_exec to run a process in the container that will talk to the MCP server over the MCP protocol (Streamable HTTP transport). The server is available at MCP_SERVER_URL with authentication token MCP_SERVER_TOKEN.

Important: MCP sessions must be initialized (session.initialize()) before you can use tools, list resources, etc. When used in one-off Python scripts, the session will be closed at the end of the script.

{GRADER_COMMON_INSTRUCTIONS}

{MCP_HTTP_CONNECTION_INSTRUCTIONS}"""
            else:
                system = f"""You are a strict grader evaluating a code critique.

Grade the critique, then submit your result by invoking the grader_submit server's submit_result tool.

{GRADER_COMMON_INSTRUCTIONS}"""

            # Build handlers list, add bootstrap for HTTP mode
            handlers_list: list[BaseHandler] = []

            # Bootstrap disabled - example code is embedded in system prompt instead
            # if http_mode:
            #     # Add bootstrap to inspect MCP server via mcptools
            #     builder = TypedBootstrapBuilder.for_server(runtime_server)
            #     bootstrap_calls = make_grader_http_bootstrap_calls(wiring, builder)
            #     handlers_list.append(SequenceHandler([InjectItems(items=bootstrap_calls)]))

            handlers_list.extend(
                [
                    AbortIf(should_abort=lambda: grader_state.result is not None),
                    *build_props_handlers(
                        transcript_id=transcript_id,
                        verbose_prefix=(
                            f"[GRADER {str(transcript_id)[:8]} {snapshot_split} {input_data.snapshot_slug}] "
                            if verbose
                            else None
                        ),
                        servers=servers,
                        max_lines=max_lines,
                    ),
                    *extra_handlers,
                ]
            )

            # Add turn limit handler if max_turns is specified
            if max_turns is not None:
                handlers_list.append(MaxTurnsHandler(max_turns=max_turns))

            agent = await Agent.create(
                mcp_client=mcp_client,
                client=client,
                handlers=handlers_list,
                dynamic_instructions=handle.render_agent_dynamic_instructions,
                parallel_tool_calls=True,
                reasoning_summary=ReasoningSummary.detailed,
                tool_policy=RequireAnyTool(),
            )
            agent.insert_messages([SystemMessage.text(system), UserMessage.text(prompt)])
            await agent.run()


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
    docker_client: aiodocker.Docker,
    extra_handlers: tuple[BaseHandler, ...] = (),
    verbose: bool = False,
    max_lines: int = DEFAULT_MAX_LINES,
    max_turns: int | None = None,
) -> UUID:
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
        Grader run ID
    """
    # Generate unique IDs for this run
    run_id = uuid4()
    transcript_id = uuid4()

    # Phase 1: Write initial run and fetch critique (BEFORE agent runs)
    with get_session() as session:
        # Fetch snapshot to get split for verbose prefix
        snapshot = session.query(Snapshot).filter_by(slug=input_data.snapshot_slug).one()
        snapshot_split = snapshot.split

        # Build canonical issues snapshot for tracking (convert MCP models to DB models)
        canonical_snapshot = CanonicalIssuesSnapshot(
            true_positives=[tp_to_db(tp) for tp in canonical_tps],
            false_positives=[fp_to_db(fp) for fp in canonical_fps],
        )

        session.add(
            DBGraderRun(
                id=run_id,
                transcript_id=transcript_id,
                snapshot_slug=input_data.snapshot_slug,
                model=client.model,
                critique_id=input_data.critique_id,
                prompt_optimization_run_id=input_data.prompt_optimization_run_id,
                canonical_issues_snapshot=canonical_snapshot,
                output=None,  # Will be set in Phase 2
            )
        )
        session.commit()
        logger.info(
            f"Created initial grader run in DB: {run_id=}, {transcript_id=}, snapshot_slug={input_data.snapshot_slug}"
        )

        # Fetch critique from database (use DB model directly)
        critique_orm = _get_required_critique(session, input_data.critique_id)
        critique_payload_db = critique_orm.payload

        # Extract reviewed files from critic run while still in session (for scope filtering)
        # TODO: Clean up path propagation - reviewed_files is extracted here, passed through
        # GradeInputs, then used in both build_grader_submit_tools (for validation) and
        # grade_critique_by_id (for prompt filtering). Consider refactoring to single source
        # or making the critique → files relationship more explicit.
        reviewed_files: set[Path] | None = None
        if critique_orm.critic_run:
            reviewed_files = {Path(f) for f in critique_orm.critic_run.files}

    # Convert critique issues to CritiqueInputIssue (access DB model fields directly)
    critique_typed = [
        CritiqueInputIssue(
            id=InputIssueID(issue.id),
            rationale=Rationale(issue.rationale),
            occurrences=[
                Occurrence(
                    files=[
                        FileOccurrence(
                            path=Path(fo.path),
                            ranges=[LineRange(start_line=r.start_line, end_line=r.end_line) for r in fo.ranges]
                            if fo.ranges
                            else None,
                        )
                        for fo in occ.files
                    ],
                    note=occ.note,
                )
                for occ in issue.occurrences
            ],
        )
        for issue in critique_payload_db.issues
    ]

    # Build grader inputs and state
    grader_state = GradeSubmitState()
    inputs = GradeInputs(
        snapshot_slug=input_data.snapshot_slug, critique=critique_payload_db, reviewed_files=reviewed_files
    )

    # Run agent with either HTTP or in-proc server based on toggle
    logger.info(f"HTTP mode enabled: {USE_MCP_HTTP}")
    await _run_grader_agent(
        grader_state=grader_state,
        inputs=inputs,
        workspace_root=hydrated_specimen.content_root,
        docker_client=docker_client,
        canonical_tps=canonical_tps,
        critique_typed=critique_typed,
        canonical_fps=canonical_fps,
        client=client,
        transcript_id=transcript_id,
        snapshot_split=snapshot_split,
        input_data=input_data,
        verbose=verbose,
        extra_handlers=extra_handlers,
        http_mode=USE_MCP_HTTP,
        max_lines=max_lines,
        max_turns=max_turns,
    )

    if grader_state.result is None:
        raise GraderDidNotSubmitError("Grader did not submit result")

    # Phase 2: Update run with output
    with get_session() as session:
        found_run = session.get(DBGraderRun, run_id)
        assert found_run is not None, f"Grader run {run_id} not found in database"
        # Convert MCP model to DB model for storage
        found_run.output = grade_submit_input_to_db(grader_state.result)
        session.commit()
        logger.info(f"Updated grader run in DB: {transcript_id=}, snapshot_slug={input_data.snapshot_slug}")

    return run_id


async def grade_critique_by_id(
    session: Session,
    critique_id: UUID,
    client: OpenAIModelProto,
    docker_client: aiodocker.Docker,
    prompt_optimization_run_id: UUID | None = None,
    verbose: bool = False,
    max_turns: int | None = None,
) -> UUID:
    """Grade critique by ID, return grader_run_id.

    Args:
        session: Database session (caller manages transaction)
        critique_id: ID of critique to grade
        client: OpenAI client
        prompt_optimization_run_id: Optional link to prompt optimization session
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

    # Filter TPs/FPs by critic scope
    if critique.critic_run:
        reviewed_files = {Path(f) for f in critique.critic_run.files}

        # Only include TPs where at least one occurrence is catchable from reviewed files
        original_tp_count = len(canonical_tps)
        canonical_tps = [
            tp for tp in canonical_tps if any(should_catch_occurrence(occ, reviewed_files) for occ in tp.occurrences)
        ]

        # Raise error if no TPs are catchable from reviewed files
        if original_tp_count > 0 and len(canonical_tps) == 0:
            raise ValueError(
                f"Cannot grade: 0/{original_tp_count} TPs catchable from reviewed files {sorted(str(f) for f in reviewed_files)}"
            )

        # Only include FPs where at least one occurrence is relevant to reviewed files
        canonical_fps = [
            fp for fp in canonical_fps if any(should_show_fp_occurrence(occ, reviewed_files) for occ in fp.occurrences)
        ]

    # Create grader input
    grader_input = GraderInput(
        snapshot_slug=snapshot_slug, critique_id=critique_id, prompt_optimization_run_id=prompt_optimization_run_id
    )

    # Hydrate source code only (not issues - already loaded from DB)
    hydrator = SnapshotHydrator.from_env()
    async with hydrator.hydrate(snapshot_slug) as hydrated:
        # Execute grader run with explicit canonical issues
        return await run_grader(
            input_data=grader_input,
            client=client,
            hydrated_specimen=hydrated,
            canonical_tps=canonical_tps,
            canonical_fps=canonical_fps,
            docker_client=docker_client,
            verbose=verbose,
            max_turns=max_turns,
        )
