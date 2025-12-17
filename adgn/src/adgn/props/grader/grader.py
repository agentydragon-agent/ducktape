"""Grader MCP server and GradeSubmitPayload models.

Defines structured output used by critique grader:
(specimen canonical issues + input critique JSON → metrics + markdown summary)
AND a tiny FastMCP server that accepts exactly one submission per run via
submit_result.
"""

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import tempfile
from typing import cast
from uuid import UUID, uuid4

import aiodocker
from fastmcp.client import Client
from fastmcp.exceptions import ToolError
from fastmcp.resources import FunctionResource
from fastmcp.server.auth import AuthProvider
from fastmcp.tools import FunctionTool
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from adgn.agent.agent import Agent
from adgn.agent.bootstrap import TypedBootstrapBuilder, docker_exec_call_mounted
from adgn.agent.handler import AbortIf, BaseHandler, RedirectOnTextMessageHandler, SequenceHandler
from adgn.agent.loop_control import AllowAnyToolOrTextMessage, InjectItems
from adgn.agent.turn_limit import MaxTurnsExceededError, MaxTurnsHandler
from adgn.mcp._shared.mounted import Mounted
from adgn.mcp._shared.types import SimpleOk
from adgn.mcp.enhanced import EnhancedFastMCP
from adgn.openai_utils.model import OpenAIModelProto, SystemMessage, UserMessage
from adgn.openai_utils.types import ReasoningSummary
from adgn.props.agent_setup import AgentEnvironment, build_props_handlers
from adgn.props.cli.common_options import DEFAULT_MAX_LINES
from adgn.props.critic.models import CriticSubmitPayload, ReportedIssue as ReportedIssueMCP
from adgn.props.critic.persistence import convert_reported_occurrence_orm_to_mcp
from adgn.props.db import get_session
from adgn.props.db.config import DatabaseConfig
from adgn.props.db.models import (
    CanonicalIssuesSnapshot,
    CriticRun,
    GraderRun as DBGraderRun,
    GraderRunStatus,
    ReportedIssue,
    Snapshot,
)
from adgn.props.display import short_uuid
from adgn.props.docker_env import PropertiesDockerCompositor
from adgn.props.grader.exceptions import GraderDidNotSubmitError
from adgn.props.grader.models import (
    CritiqueInputIssue,
    FalsePositiveID,
    GraderInput,
    GraderSuccess,
    GradeValidationContext,
    KnownFalsePositive,
    OccurrenceMatch,
    OccurrenceResult,
    TruePositiveID,
    TruePositiveIssue,
    UnknownIssue,
)
from adgn.props.grader.persistence import fp_to_db, tp_to_db
from adgn.props.grader.submit_server import GraderSubmitServer as GraderSubmitServerSQL
from adgn.props.grader.user_manager import GraderUserManager
from adgn.props.hydration import SnapshotHydrator
from adgn.props.ids import InputIssueID, SnapshotSlug
from adgn.props.models.critic_scopes import AllFilesScope, CriticScopeSpec, ExplicitFileScope
from adgn.props.models.true_positive import LineRange, Occurrence, should_catch_occurrence, should_show_fp_occurrence
from adgn.props.prompts.schemas import build_input_schemas_json
from adgn.props.prompts.util import render_prompt_template
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


class GradeSubmitState:
    """Container for submitted grading results."""

    result: GraderSuccess | None = None


@dataclass(frozen=True)
class GradeInputs:
    """Grading context: snapshot slug, critique issues, and ground truth data."""

    snapshot_slug: SnapshotSlug
    # Ground truth data for serving as resources
    canonical_tps: list[TruePositiveIssue]
    critique_typed: list[CritiqueInputIssue]  # Issues from critic (loaded from normalized tables)
    canonical_fps: list[KnownFalsePositive]
    scope: CriticScopeSpec  # Critic scope for validation (resolved inline when needed)


# MCP Resource URIs (unprefixed - used in server registration and prompts)
GRADER_SNAPSHOT_SLUG_RESOURCE_URI = "resource://grader_submit/snapshot_slug"
GRADER_CANONICAL_TPS_RESOURCE_URI = "resource://grader_submit/canonical_tps"
GRADER_CRITIQUE_ISSUES_RESOURCE_URI = "resource://grader_submit/critique_issues"
GRADER_KNOWN_FPS_RESOURCE_URI = "resource://grader_submit/known_fps"


def build_grade_from_json_prompt(*, submit_tool_name: str, compositor: PropertiesDockerCompositor) -> str:
    """Compose grader prompt that reads ground truth from MCP resources."""
    schemas_json = build_input_schemas_json(
        [Occurrence, LineRange, ReportedIssueMCP, CriticSubmitPayload, OccurrenceResult, OccurrenceMatch]
    )

    return render_prompt_template(
        "prompts/grade_from_json.j2.md",
        canonical_tps_resource_uri=GRADER_CANONICAL_TPS_RESOURCE_URI,
        critique_issues_resource_uri=GRADER_CRITIQUE_ISSUES_RESOURCE_URI,
        known_fps_resource_uri=GRADER_KNOWN_FPS_RESOURCE_URI,
        submit_tool_name=submit_tool_name,
        working_dir=compositor.working_dir,
        definitions_container_dir=compositor.definitions_container_dir,
        schemas_json=schemas_json,
    )


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

    # Resource attributes (stashed results of @resource decorator - single source of truth for URI access)
    snapshot_slug_resource: FunctionResource
    canonical_tps_resource: FunctionResource
    critique_issues_resource: FunctionResource
    known_fps_resource: FunctionResource

    # Tool reference (assigned in __init__)
    submit_result_tool: FunctionTool

    def __init__(
        self, state: GradeSubmitState, inputs: GradeInputs, grader_run_id: UUID, auth: AuthProvider | None = None
    ):
        """Create grader submit server with state container and validation context.

        Args:
            state: State container for submitted result.
            inputs: Grading context (snapshot slug, critique, and ground truth).
            grader_run_id: Grader run ID (for writing status to database).
            auth: Auth provider for HTTP mode (None for inproc).
        """
        super().__init__("Grader Submit Server", instructions=GRADER_SUBMIT_INSTRUCTIONS, auth=auth)
        self._grader_run_id = grader_run_id

        # Register snapshot_slug resource and stash the result
        async def get_snapshot_slug() -> str:
            """Get the snapshot slug for this grader run.

            The snapshot source code is mounted at /snapshots/<slug>.
            """
            return str(inputs.snapshot_slug)

        self.snapshot_slug_resource = cast(
            FunctionResource, self.resource(GRADER_SNAPSHOT_SLUG_RESOURCE_URI)(get_snapshot_slug)
        )

        # Register ground truth resources (FastMCP handles Pydantic model serialization)
        async def get_canonical_tps() -> list[TruePositiveIssue]:
            """Get canonical true positive issues (JSON array).

            These are the ground truth issues that should be found by the critic.
            """
            return inputs.canonical_tps

        self.canonical_tps_resource = cast(
            FunctionResource, self.resource(GRADER_CANONICAL_TPS_RESOURCE_URI)(get_canonical_tps)
        )

        async def get_critique_issues() -> list[CritiqueInputIssue]:
            """Get input critique issues (JSON array).

            These are the issues reported by the critic being graded.
            """
            return inputs.critique_typed

        self.critique_issues_resource = cast(
            FunctionResource, self.resource(GRADER_CRITIQUE_ISSUES_RESOURCE_URI)(get_critique_issues)
        )

        async def get_known_fps() -> list[KnownFalsePositive]:
            """Get known false positives (JSON array).

            These are patterns that should explicitly NOT be flagged.
            """
            return inputs.canonical_fps

        self.known_fps_resource = cast(FunctionResource, self.resource(GRADER_KNOWN_FPS_RESOURCE_URI)(get_known_fps))

        # Load ORM snapshot from database for ground truth issues
        with get_session() as session:
            snapshot_orm = session.query(Snapshot).filter_by(slug=inputs.snapshot_slug).one()

            # Build validation context using factory method (INPUT BOUNDARY - typed IDs created here)
            # Pass scope for filtering (resolved inline in factory method)
            context = GradeValidationContext.from_specimen_and_critique(
                snapshot_orm, inputs.critique_typed, scope=inputs.scope
            )

        # Register tool - name derived from function name
        # Tool signature matches GraderSuccess structure (without tag field)
        class GradeSubmitPayload(BaseModel):
            """Complete grading submission with per-occurrence results."""

            occurrence_results: list[OccurrenceResult] = Field(
                description="Per-occurrence grading results. One entry per catchable occurrence."
            )

            unknowns: list[UnknownIssue] = Field(
                default_factory=list,
                description="Input issues with novel aspects not matched to canonical issues (TPs or FPs)",
            )

            summary: Rationale = Field(
                description="High-level summary of grading. Cross-cutting patterns, overall assessment."
            )

            model_config = ConfigDict(extra="forbid", frozen=True)

        async def submit_result(payload: GradeSubmitPayload) -> SimpleOk:
            """Submit the final grading result with per-occurrence assessment."""
            # Validate unknowns: all IDs must be from input critique
            unknown_ids = {issue.input_id for issue in payload.unknowns}
            invalid_unknowns = unknown_ids - context.allowed_input_ids
            if invalid_unknowns:
                raise ToolError(
                    f"Unknown issue IDs not from input critique: {sorted(str(id) for id in invalid_unknowns)}"
                )

            # Validate ground truth coverage: every TP occurrence in scope must have a result
            # Expected occurrences were computed when the context was built
            expected_occurrences = context.expected_occurrences

            # Collect submitted occurrences
            submitted_occurrences = {(str(result.tp_id), result.occurrence_id) for result in payload.occurrence_results}

            # Check for missing occurrences
            missing_occurrences = expected_occurrences - submitted_occurrences
            if missing_occurrences:
                missing_list = sorted(f"{tp_id}/{occ_id}" for tp_id, occ_id in missing_occurrences)
                raise ToolError(
                    f"Missing grading results for {len(missing_occurrences)} TP occurrence(s) in scope. "
                    f"You must provide a result for EVERY catchable occurrence. "
                    f"Missing: {missing_list[:10]}"
                    + (f" (and {len(missing_list) - 10} more)" if len(missing_list) > 10 else "")
                )

            # Check for unexpected occurrences (should not happen, but validate anyway)
            unexpected_occurrences = submitted_occurrences - expected_occurrences
            if unexpected_occurrences:
                unexpected_list = sorted(f"{tp_id}/{occ_id}" for tp_id, occ_id in unexpected_occurrences)
                raise ToolError(
                    f"Unexpected TP occurrence(s) not in scope: {unexpected_list[:10]}"
                    + (f" (and {len(unexpected_list) - 10} more)" if len(unexpected_list) > 10 else "")
                )

            # Collect all input IDs that were matched to TPs (with nonzero credit)
            tp_matched_ids = {
                match.input_id
                for result in payload.occurrence_results
                for match in result.matched_by
                if match.credit > 0.0
            }

            # Validate completeness: every critique issue must appear exactly once
            # Categories: TP matches (with nonzero credit) OR unknowns
            accounted_for = tp_matched_ids | unknown_ids
            unaccounted = context.allowed_input_ids - accounted_for
            overlaps = tp_matched_ids & unknown_ids

            if unaccounted:
                raise ToolError(
                    f"Input critique issues not accounted for (not in TP matches or unknowns): "
                    f"{sorted(str(id) for id in unaccounted)}"
                )

            if overlaps:
                raise ToolError(
                    f"Input critique issues appear in multiple categories (both TP matches and unknowns): "
                    f"{sorted(str(id) for id in overlaps)}"
                )

            # Build GraderSuccess from payload (tag is set automatically)
            result = GraderSuccess(
                occurrence_results=payload.occurrence_results, unknowns=payload.unknowns, summary=payload.summary
            )

            # Store in state for backwards compatibility
            state.result = result

            # Write to database (consistent with HTTP mode)
            with get_session() as session:
                grader_run = session.get(DBGraderRun, self._grader_run_id)
                if grader_run is None:
                    raise ToolError(f"Grader run {self._grader_run_id} not found in database")

                # Mark run as completed
                grader_run.status = GraderRunStatus.COMPLETED
                # Store summary as markdown notes
                grader_run.notes_md = result.summary
                # Note: output field left as None - grading results are in grading_decisions table
                session.commit()

            return SimpleOk(ok=True)

        self.submit_result_tool = self.flat_model()(submit_result)


# Rich renderer removed - old GradeSubmitInput model no longer used
# Per-occurrence grading results are stored in GraderSuccess model


class GraderCompositor(PropertiesDockerCompositor):
    """Compositor with grader servers pre-mounted (inproc mode only).

    Inherits from PropertiesDockerCompositor, which provides:
    - runtime: Docker exec server (mounted by parent class)

    Adds:
    - grader_submit: Grader submission server

    Note: This handles only inproc mode. HTTP mode is handled separately.
    """

    # Mounted server attributes (runtime inherited, grader_submit added here)
    grader_submit: Mounted[GraderSubmitServer]

    def __init__(
        self,
        snapshot_slug: SnapshotSlug,
        docker_client: aiodocker.Docker,
        hydrator: SnapshotHydrator,
        grader_state: GradeSubmitState,
        inputs: GradeInputs,
        grader_run_id: UUID,
        **kwargs,
    ):
        """Create compositor with grader dependencies.

        Args:
            snapshot_slug: Snapshot slug to hydrate and mount at /snapshots/<slug>.
            docker_client: Async Docker client (managed by caller).
            hydrator: Snapshot hydrator (parent class handles hydration).
            grader_state: Grader submit state container.
            inputs: Grading context (snapshot slug and critique).
            grader_run_id: Grader run ID (for writing status to database).
            **kwargs: Additional arguments passed to PropertiesDockerCompositor
                (mount_properties, db_conn, extra_binds, network_mode, extra_env)
                Note: ephemeral is hardcoded to False
        """
        self._snapshot_slug = snapshot_slug
        self._docker_client = docker_client
        self._hydrator = hydrator
        self._grader_state = grader_state
        self._inputs = inputs
        self._grader_run_id = grader_run_id
        self._kwargs = kwargs
        self._workspace_tmpdir: tempfile.TemporaryDirectory | None = None

    async def __aenter__(self):
        """Start compositor and mount servers."""
        # Create temporary workspace for grader artifacts
        self._workspace_tmpdir = tempfile.TemporaryDirectory(prefix="grader_workspace_")
        workspace_path = Path(self._workspace_tmpdir.__enter__())

        # Initialize parent compositor with temp workspace
        # ephemeral=False is hardcoded so grader can persist temporary analysis artifacts
        super().__init__(
            workspace_path,
            self._docker_client,
            hydrator=self._hydrator,
            snapshot_slugs=[self._snapshot_slug],
            workspace_mode="rw",  # Workspace is read-write for agent artifacts
            ephemeral=False,  # Hardcoded: grader needs persistent workspace
            **self._kwargs,
        )

        # Start parent compositor (mounts resources, compositor_meta, runtime)
        await super().__aenter__()

        # Mount grader submit server (needs grader_run_id to write to database)
        if self._grader_run_id is None:
            raise ValueError("grader_run_id is required for GraderCompositor")

        self.grader_submit = await self.mount_inproc(
            "grader_submit", GraderSubmitServer(self._grader_state, self._inputs, self._grader_run_id), pinned=True
        )

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Cleanup: stop compositor and remove temp workspace."""
        try:
            return await super().__aexit__(exc_type, exc_val, exc_tb)
        finally:
            # Clean up temporary workspace
            if self._workspace_tmpdir is not None:
                self._workspace_tmpdir.__exit__(None, None, None)


# =============================================================================
# Agent Execution
# =============================================================================


async def _run_grader_agent(
    *,
    grader_state: GradeSubmitState,
    inputs: GradeInputs,
    hydrator: SnapshotHydrator,
    docker_client: aiodocker.Docker,
    canonical_tps: list[TruePositiveIssue],
    critique_typed: list[CritiqueInputIssue],
    canonical_fps: list[KnownFalsePositive],
    client: OpenAIModelProto,
    transcript_id: UUID,
    input_data: GraderInput,
    verbose: bool,
    extra_handlers: tuple[BaseHandler, ...],
    db_config: DatabaseConfig,
    http_mode: bool = False,
    max_lines: int = DEFAULT_MAX_LINES,
    max_turns: int,
    grader_run_id: UUID,
) -> None:
    """Run the grader agent.

    Args:
        hydrator: Snapshot hydrator for mounting snapshot source code
        http_mode: If True, grader_submit is exposed via HTTP (managed by GraderAgentEnvironment).
            If False, grader_submit is mounted in compositor (which handles snapshot hydration).
        canonical_tps: True positive issues from specimen
        critique_typed: Issues from the critique being graded
        canonical_fps: Known false positives from specimen

    Returns:
        GraderSuccess if completed, GraderMaxTurnsExceeded if agent ran out of turns
    """
    # Derive snapshot_slug and snapshot_split from input_data.critic_run_id
    with get_session() as session:
        critic_run = session.get(CriticRun, input_data.critic_run_id)
        if critic_run is None:
            raise ValueError(f"Critic run {input_data.critic_run_id} not found")

        snapshot_slug = critic_run.snapshot_slug
        snapshot = session.get(Snapshot, snapshot_slug)
        if snapshot is None:
            raise ValueError(f"Snapshot {snapshot_slug} not found")
        snapshot_split = snapshot.split
    # Choose compositor based on http_mode
    # HTTP mode: use GraderAgentEnvironment (manages user, HTTP server, and container)
    #            Network: PROPS_NETWORK_NAME, snapshots mounted at /snapshots/<slug>/
    #            Server: SQL-based GraderSubmitServerSQL (agent writes to PostgreSQL)
    # In-proc mode: use GraderCompositor (runtime + grader_submit mounted in-proc)
    #               Network: "none" (isolated, no network access needed)
    #               Server: State-based GraderSubmitServer (in-memory state)
    #               Compositor handles temp workspace and snapshot hydration internally
    comp_ctx: GraderAgentEnvironment | GraderCompositor

    if http_mode:
        # HTTP mode: Use GraderAgentEnvironment (manages user, HTTP server, container)
        comp_ctx = GraderAgentEnvironment(
            snapshot_slug=snapshot_slug,
            docker_client=docker_client,
            hydrator=hydrator,
            grader_run_id=grader_run_id,
            critic_run_id=input_data.critic_run_id,
            db_config=db_config,
        )
    else:
        comp_ctx = GraderCompositor(
            snapshot_slug=snapshot_slug,
            docker_client=docker_client,
            hydrator=hydrator,
            grader_state=grader_state,
            inputs=inputs,
            grader_run_id=grader_run_id,
            mount_properties=False,
            # ephemeral=False is hardcoded in GraderCompositor
            # network_mode defaults to "none" (isolated)
        )

    async with comp_ctx as handle:
        # Build prompt - tool name differs based on mode:
        # - HTTP mode: SQL-based server uses "grader_submit" tool name directly
        # - In-proc mode: State-based server via compositor, use Mounted.tool_name() helper (adds prefix)
        if http_mode:
            # SQL-based server tool name (from GraderSubmitServerSQL)
            submit_tool_name = "grader_submit"
        else:
            # Type narrowing: handle is GraderCompositor in else branch
            assert isinstance(handle, GraderCompositor)
            submit_tool_name = handle.grader_submit.tool_name(handle.grader_submit.server.submit_result_tool)

        prompt = build_grade_from_json_prompt(submit_tool_name=submit_tool_name, compositor=handle)

        # Note: resources and compositor_meta are auto-mounted by base Compositor
        async with Client(handle) as mcp_client:
            # Build system prompt
            if http_mode:
                # SQL workflow: render grader_system.j2.md template
                system = render_prompt_template("grader/prompts/grader_system.j2.md")
            else:
                # Legacy workflow: use inline system prompt
                system = f"""You are a strict grader evaluating a code critique.

Grade the critique, then submit your result by invoking the grader_submit server's submit_result tool.

The snapshot slug for this grader run is available at the MCP resource `{GRADER_SNAPSHOT_SLUG_RESOURCE_URI}`.

{GRADER_COMMON_INSTRUCTIONS}"""

            # Build handlers list, add bootstrap
            handlers_list: list[BaseHandler] = []

            # Bootstrap: read snapshot_slug from grader_submit server resource
            builder = TypedBootstrapBuilder.for_server(handle.runtime.server)

            if http_mode:
                # TODO: demonstrate proper tool calling (CallToolResult is not json.dump-able)
                bootstrap_script = f"""
import asyncio
import json
from adgn.props.agent_helpers import mcp_client_from_env

async def bootstrap():
    async with mcp_client_from_env() as (session, init_result):
        print("=== MCP Server Initialization ===")
        print(json.dumps(init_result.model_dump(mode="json"), indent=2))

        tools = await session.list_tools()
        print("=== Available Tools ===")
        for tool in tools:
            print(json.dumps(tool.model_dump(mode="json"), indent=2))

        # Read resources in order
        resources = [
            ("Snapshot Slug", "{GRADER_SNAPSHOT_SLUG_RESOURCE_URI}"),
            ("Canonical True Positives", "{GRADER_CANONICAL_TPS_RESOURCE_URI}"),
            ("Critique Issues", "{GRADER_CRITIQUE_ISSUES_RESOURCE_URI}"),
            ("Known False Positives", "{GRADER_KNOWN_FPS_RESOURCE_URI}"),
        ]
        for label, uri in resources:
            print(f"=== {{label}} ===")
            result = await session.read_resource(uri)
            print(json.dumps(result.model_dump(mode="json"), indent=2))

asyncio.run(bootstrap())
"""
                logger.info("Grader bootstrap: executing docker bootstrap script for MCP initialization")
                bootstrap_calls = [
                    docker_exec_call_mounted(
                        builder, handle.runtime, cmd=["python3", "-c", bootstrap_script], timeout_ms=15_000
                    )
                ]
                handlers_list.append(SequenceHandler([InjectItems(items=bootstrap_calls)]))
            else:
                # Inproc mode: grader_submit is mounted in compositor - use resources server
                # Type narrowing: handle is GraderCompositor in inproc mode
                assert isinstance(handle, GraderCompositor)
                bootstrap_calls = [
                    # Read snapshot slug from grader_submit server resource
                    builder.read_resource(
                        handle.resources,
                        server=handle.grader_submit.prefix,
                        uri=handle.grader_submit.server.snapshot_slug_resource.uri,
                        max_bytes=256,
                    ),
                    # Read ground truth resources
                    builder.read_resource(
                        handle.resources,
                        server=handle.grader_submit.prefix,
                        uri=handle.grader_submit.server.canonical_tps_resource.uri,
                        max_bytes=1_000_000,  # Large enough for canonical TPs JSON
                    ),
                    builder.read_resource(
                        handle.resources,
                        server=handle.grader_submit.prefix,
                        uri=handle.grader_submit.server.critique_issues_resource.uri,
                        max_bytes=1_000_000,  # Large enough for critique issues JSON
                    ),
                    builder.read_resource(
                        handle.resources,
                        server=handle.grader_submit.prefix,
                        uri=handle.grader_submit.server.known_fps_resource.uri,
                        max_bytes=1_000_000,  # Large enough for known FPs JSON
                    ),
                ]
                handlers_list.append(SequenceHandler([InjectItems(items=bootstrap_calls)]))

            # Define abort condition: check database status for grader completion
            def _grader_ready_state() -> bool:
                """Check if grader run is completed in database.

                Used by AbortIf handler to stop agent loop when grading is done.
                Queries database status - works for both HTTP and in-proc modes.
                """
                with get_session() as session:
                    found_run = session.get(DBGraderRun, grader_run_id)
                    return found_run is not None and found_run.status in (
                        GraderRunStatus.COMPLETED,
                        GraderRunStatus.MAX_TURNS_EXCEEDED,
                    )

            handlers_list.extend(
                [
                    AbortIf(should_abort=_grader_ready_state),
                    *await build_props_handlers(
                        transcript_id=transcript_id,
                        verbose_prefix=(
                            f"[GRADER {short_uuid(transcript_id)} {snapshot_split} {snapshot_slug}] "
                            if verbose
                            else None
                        ),
                        compositor=handle,
                        max_lines=max_lines,
                    ),
                    RedirectOnTextMessageHandler(
                        reminder_message=(
                            "You are a grader agent. Your grading has not yet been submitted to the MCP server. "
                            "Your task is to evaluate the given input critique by comparing it against canonical findings "
                            "using the provided MCP tools, then submit your grading. "
                            "This is not an interactive workflow - complete your analysis and submit the grading via the MCP tool. "
                            "Do not attempt to submit your grade by sending a text message - use the tool."
                        )
                    ),
                    *extra_handlers,
                    MaxTurnsHandler(max_turns=max_turns),
                ]
            )

            agent = await Agent.create(
                mcp_client=mcp_client,
                client=client,
                handlers=handlers_list,
                dynamic_instructions=handle.render_agent_dynamic_instructions,
                parallel_tool_calls=True,
                reasoning_summary=ReasoningSummary.detailed,
                tool_policy=AllowAnyToolOrTextMessage(),
            )
            agent.insert_messages([SystemMessage.text(system), UserMessage.text(prompt)])
            try:
                await agent.run()

                # Agent completed normally - validate database status
                with get_session() as session:
                    found_run = session.get(DBGraderRun, grader_run_id)
                    if found_run is None:
                        raise GraderDidNotSubmitError(f"Grader run {grader_run_id} not found in database")
                    if found_run.status != GraderRunStatus.COMPLETED:
                        raise GraderDidNotSubmitError(
                            f"Grader run {grader_run_id} completed but status is {found_run.status}, expected COMPLETED"
                        )

                # In-proc mode: also validate in-memory state (HTTP mode doesn't set this)
                if not http_mode and grader_state.result is None:
                    raise GraderDidNotSubmitError("Grader did not submit result (in-memory state not set)")

                # Both modes have written to the database - nothing more to do
                return
            except MaxTurnsExceededError:
                # Agent ran out of turns - mark as max_turns_exceeded in database
                # NOTE: max_turns_exceeded is taken as recall=0.0 (see query_builders.py:803-806)
                logger.warning(
                    f"Grader hit max turns limit ({max_turns}) for {snapshot_slug}, "
                    f"transcript_id={short_uuid(transcript_id)}"
                )
                with get_session() as session:
                    found_run = session.get(DBGraderRun, grader_run_id)
                    if found_run:
                        found_run.status = GraderRunStatus.MAX_TURNS_EXCEEDED
                        session.commit()
                return


# =============================================================================
# Grader Run Function
# =============================================================================


async def run_grader(
    *,
    input_data: GraderInput,
    client: OpenAIModelProto,
    hydrator: SnapshotHydrator,
    canonical_tps: list[TruePositiveIssue],
    canonical_fps: list[KnownFalsePositive],
    docker_client: aiodocker.Docker,
    db_config: DatabaseConfig,
    extra_handlers: tuple[BaseHandler, ...] = (),
    verbose: bool = False,
    max_lines: int = DEFAULT_MAX_LINES,
    max_turns: int,
) -> UUID:
    """Run grader agent: evaluate critique against ground truth, persist to DB.

    Args:
        input_data: Grader input with critic_run_id
        client: OpenAI client
        hydrator: Snapshot hydrator for mounting snapshot source code
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
        # Fetch critic run to get snapshot_slug
        critic_run = session.get(CriticRun, input_data.critic_run_id)
        if critic_run is None:
            raise ToolError(f"Critic run {input_data.critic_run_id} not found in database")

        snapshot_slug = critic_run.snapshot_slug

        # Build canonical issues snapshot for tracking (convert MCP models to DB models)
        canonical_snapshot = CanonicalIssuesSnapshot(
            true_positives=[tp_to_db(tp) for tp in canonical_tps],
            false_positives=[fp_to_db(fp) for fp in canonical_fps],
        )

        session.add(
            DBGraderRun(
                id=run_id,
                transcript_id=transcript_id,
                snapshot_slug=snapshot_slug,
                model=client.model,
                critic_run_id=input_data.critic_run_id,
                prompt_optimization_run_id=input_data.prompt_optimization_run_id,
                canonical_issues_snapshot=canonical_snapshot,
                status=GraderRunStatus.IN_PROGRESS,  # Will be updated to COMPLETED by submit
                # output left as None (nullable) - results are in grading_decisions table
            )
        )
        session.commit()
        logger.info(f"Created initial grader run in DB: {run_id=}, {transcript_id=}, snapshot_slug={snapshot_slug}")

        # Load reported issues from normalized table
        reported_issues = session.query(ReportedIssue).filter_by(critic_run_id=input_data.critic_run_id).all()

        # Get critic scope from example (via critic_run -> example relationship)
        # Scope is stored in Example table and referenced via (snapshot_slug, scope_hash) FK
        critic_scope = critic_run.example_obj.scope

    # Convert reported issues to CritiqueInputIssue (build from ReportedIssue ORM)
    # Use shared conversion function that groups locations by file
    critique_typed = [
        CritiqueInputIssue(
            id=InputIssueID(issue.issue_id),
            rationale=Rationale(issue.rationale),
            occurrences=[convert_reported_occurrence_orm_to_mcp(occ) for occ in issue.occurrences],
        )
        for issue in reported_issues
    ]

    # Build grader inputs and state
    grader_state = GradeSubmitState()
    inputs = GradeInputs(
        snapshot_slug=snapshot_slug,
        canonical_tps=canonical_tps,
        critique_typed=critique_typed,
        canonical_fps=canonical_fps,
        scope=critic_scope,
    )

    # Run agent with either HTTP or in-proc server based on toggle
    logger.info(f"HTTP mode enabled: {USE_MCP_HTTP}")
    await _run_grader_agent(
        grader_state=grader_state,
        inputs=inputs,
        hydrator=hydrator,
        docker_client=docker_client,
        canonical_tps=canonical_tps,
        critique_typed=critique_typed,
        canonical_fps=canonical_fps,
        client=client,
        transcript_id=transcript_id,
        input_data=input_data,
        verbose=verbose,
        extra_handlers=extra_handlers,
        db_config=db_config,
        http_mode=USE_MCP_HTTP,
        max_lines=max_lines,
        max_turns=max_turns,
        grader_run_id=run_id,
    )

    # Phase 2: Verify grader run was updated in database by submit server
    with get_session() as session:
        found_run = session.get(DBGraderRun, run_id)
        assert found_run is not None, f"Grader run {run_id} not found in database"
        logger.info(
            f"Grader run completed and written to DB: {transcript_id=}, snapshot_slug={snapshot_slug}, status={found_run.status}"
        )

    return run_id


async def grade_critic_run_by_id(
    session: Session,
    critic_run_id: UUID,
    client: OpenAIModelProto,
    docker_client: aiodocker.Docker,
    hydrator: SnapshotHydrator,
    db_config: DatabaseConfig,
    prompt_optimization_run_id: UUID | None = None,
    verbose: bool = False,
    max_turns: int = 200,
) -> UUID:
    """Grade critic run by ID, return grader_run_id.

    Args:
        session: Database session (caller manages transaction)
        critic_run_id: ID of critic run to grade
        client: OpenAI client
        docker_client: Async Docker client
        hydrator: Snapshot hydrator for mounting snapshot source code
        prompt_optimization_run_id: Optional link to prompt optimization session
        verbose: Enable verbose output

    Returns:
        Grader run ID
    """
    # Fetch critic run to get snapshot_slug
    critic_run = session.get(CriticRun, critic_run_id)
    if critic_run is None:
        raise ValueError(f"Critic run {critic_run_id} not found in database")

    snapshot_slug = critic_run.snapshot_slug

    # Load snapshot and issues from database (no jsonnet!)
    snapshot = session.query(Snapshot).filter_by(slug=snapshot_slug).one()

    # Get critic scope from example and resolve to file set for filtering
    # Scope is stored in Example table and referenced via (snapshot_slug, scope_hash) FK
    critic_scope = critic_run.example_obj.scope

    # Resolve scope to file set for TP/FP filtering
    if isinstance(critic_scope, AllFilesScope):
        # Load all files with issues from snapshot
        reviewed_files = snapshot.files_with_issues()
        if not reviewed_files:
            raise ValueError(
                f"Snapshot '{snapshot_slug}' has no files with ground truth issues. Cannot use AllFilesScope."
            )
    else:
        # Type narrowing: must be ExplicitFileScope
        assert isinstance(critic_scope, ExplicitFileScope)
        reviewed_files = {Path(f) for f in critic_scope.files}

    # Filter ORM models - ORM occurrences are domain models, so we can use domain model helpers directly
    original_tp_count = len(snapshot.true_positives)
    filtered_orm_tps = [
        tp
        for tp in snapshot.true_positives
        if any(should_catch_occurrence(occ, reviewed_files) for occ in tp.occurrences)
    ]
    filtered_orm_fps = [
        fp
        for fp in snapshot.false_positives
        if any(should_show_fp_occurrence(occ, reviewed_files) for occ in fp.occurrences)
    ]

    # Raise error if no TPs are catchable from reviewed files
    if original_tp_count > 0 and len(filtered_orm_tps) == 0:
        raise ValueError(
            f"Cannot grade: 0/{original_tp_count} TPs catchable from reviewed files {sorted(str(f) for f in reviewed_files)}"
        )

    # Convert only filtered ORM models to MCP models
    canonical_tps = [_tp_from_orm(tp) for tp in filtered_orm_tps]
    canonical_fps = [_fp_from_orm(fp) for fp in filtered_orm_fps]

    # Create grader input
    grader_input = GraderInput(critic_run_id=critic_run_id, prompt_optimization_run_id=prompt_optimization_run_id)

    # Execute grader run with explicit canonical issues (hydrator provided by caller)
    return await run_grader(
        input_data=grader_input,
        client=client,
        hydrator=hydrator,
        canonical_tps=canonical_tps,
        canonical_fps=canonical_fps,
        docker_client=docker_client,
        db_config=db_config,
        verbose=verbose,
        max_turns=max_turns,
    )


# =============================================================================
# Grader Agent Environment (SQL Mode)
# =============================================================================


class GraderAgentEnvironment(AgentEnvironment):
    """Agent environment for SQL-based grader with grader_submit tool.

    Provides complete environment for grader agents:
    - Temporary database user with RLS scoping (grader_agent_{run_id})
    - HTTP MCP server with grader_submit tool
    - Docker container with docker_exec
    - Hydrated snapshot mounted at /snapshots/<slug>/

    Agent workflow:
    1. Reads critique and ground truth from PostgreSQL via psql
    2. Writes grading decisions directly to PostgreSQL
    3. Calls grader_submit tool via MCP-over-HTTP when done
    4. Submit validates decisions and marks run complete

    Usage:
        async with GraderAgentEnvironment(
            snapshot_slug="ducktape/2025-11-26-00",
            docker_client=docker_client,
            hydrator=hydrator,
            grader_run_id=run_id,
            critic_run_id=critic_run_id,
        ) as compositor:
            # Run grader agent
            ...
    """

    def __init__(
        self,
        snapshot_slug: SnapshotSlug,
        docker_client: aiodocker.Docker,
        hydrator: SnapshotHydrator,
        grader_run_id: UUID,
        critic_run_id: UUID,
        db_config: DatabaseConfig,
    ):
        """Create grader agent environment.

        Args:
            snapshot_slug: Snapshot slug to hydrate and mount
            docker_client: Async Docker client
            hydrator: Snapshot hydrator
            grader_run_id: UUID of the grader run (for RLS scoping)
            critic_run_id: UUID of the critic run being graded
            db_config: Database configuration (passed via DI)
        """

        def make_user_manager() -> GraderUserManager:
            """Create temporary grader user with RLS scoping."""
            return GraderUserManager(db_config.admin, grader_run_id)

        def make_mcp_server(auth: AuthProvider) -> EnhancedFastMCP:
            """Create grader submit server (auth provided by HTTP server)."""
            return GraderSubmitServerSQL(grader_run_id=grader_run_id, critic_run_id=critic_run_id, auth=auth)

        super().__init__(
            docker_client=docker_client,
            user_manager_factory=make_user_manager,
            mcp_server_factory=make_mcp_server,
            hydrator=hydrator,
            snapshot_slugs=[snapshot_slug],
            workspace_prefix="grader_workspace_",
        )
