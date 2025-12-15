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
import shutil
import tempfile
from typing import cast
from uuid import UUID, uuid4

import aiodocker
from fastmcp.client import Client
from fastmcp.exceptions import ToolError
from fastmcp.resources import FunctionResource
from fastmcp.server.auth import AuthProvider, StaticTokenVerifier
from fastmcp.tools import FunctionTool
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from adgn.agent.agent import Agent
from adgn.agent.bootstrap import TypedBootstrapBuilder, docker_exec_call_mounted
from adgn.agent.handler import AbortIf, BaseHandler, RedirectOnTextMessageHandler, SequenceHandler
from adgn.agent.loop_control import AllowAnyToolOrTextMessage, InjectItems
from adgn.agent.turn_limit import MaxTurnsExceededError, MaxTurnsHandler
from adgn.mcp._shared.mounted import Mounted
from adgn.mcp._shared.types import MCPMountPrefix, SimpleOk
from adgn.mcp.enhanced import EnhancedFastMCP
from adgn.openai_utils.model import OpenAIModelProto, SystemMessage, UserMessage
from adgn.openai_utils.types import ReasoningSummary
from adgn.props.agent_setup import build_props_handlers
from adgn.props.cli.common_options import DEFAULT_MAX_LINES
from adgn.props.db import get_session
from adgn.props.db.config import DatabaseConfig
from adgn.props.db.models import (
    CanonicalIssuesSnapshot,
    Critique,
    DBCriticSubmitPayload,
    GraderRun as DBGraderRun,
    Snapshot,
)
from adgn.props.display import short_uuid
from adgn.props.docker_env import PropertiesDockerCompositor
from adgn.props.grader.exceptions import GraderDidNotSubmitError
from adgn.props.grader.models import (
    CritiqueInputIssue,
    FalsePositiveID,
    GraderInput,
    GraderMaxTurnsExceeded,
    GraderOutput,
    GraderSuccess,
    GradeValidationContext,
    KnownFalsePositive,
    OccurrenceResult,
    TruePositiveID,
    TruePositiveIssue,
    UnknownIssue,
)
from adgn.props.grader.persistence import fp_to_db, grader_output_to_db, tp_to_db
from adgn.props.http_compositor import PropertiesDockerCompositorHTTP
from adgn.props.hydration import SnapshotHydrator
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
    """Container for submitted grading results."""

    result: GraderSuccess | None = None


@dataclass(frozen=True)
class GradeInputs:
    """Grading context: snapshot slug, critique, and ground truth data."""

    snapshot_slug: SnapshotSlug
    critique: DBCriticSubmitPayload  # DB persistence model (not MCP I/O model)
    # Ground truth data for serving as resources
    canonical_tps: list[TruePositiveIssue]
    critique_typed: list[CritiqueInputIssue]
    canonical_fps: list[KnownFalsePositive]
    reviewed_files: set[Path] | None = None  # Files reviewed by critic (for scope filtering)


# MCP Resource URIs (unprefixed - used in server registration and prompts)
GRADER_SNAPSHOT_SLUG_RESOURCE_URI = "resource://grader_submit/snapshot_slug"
GRADER_CANONICAL_TPS_RESOURCE_URI = "resource://grader_submit/canonical_tps"
GRADER_CRITIQUE_ISSUES_RESOURCE_URI = "resource://grader_submit/critique_issues"
GRADER_KNOWN_FPS_RESOURCE_URI = "resource://grader_submit/known_fps"

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

    def __init__(self, state: GradeSubmitState, inputs: GradeInputs, auth: AuthProvider | None = None):
        """Create grader submit server with state container and validation context.

        Args:
            state: State container for submitted result.
            inputs: Grading context (snapshot slug, critique, and ground truth).
            auth: Auth provider for HTTP mode (None for inproc).
        """
        super().__init__("Grader Submit Server", instructions=GRADER_SUBMIT_INSTRUCTIONS, auth=auth)

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
            # Pass reviewed_files for scope filtering if available
            context = GradeValidationContext.from_specimen_and_critique(
                snapshot_orm, inputs.critique, reviewed_files=inputs.reviewed_files
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
            state.result = GraderSuccess(
                occurrence_results=payload.occurrence_results, unknowns=payload.unknowns, summary=payload.summary
            )
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

    # Mount prefix constant (for test infrastructure only)
    SUBMIT_PREFIX = MCPMountPrefix("grader_submit")

    # Mounted server attributes (runtime inherited, grader_submit added here)
    grader_submit: Mounted[GraderSubmitServer]

    def __init__(
        self,
        snapshot_slug: SnapshotSlug,
        docker_client: aiodocker.Docker,
        hydrator: SnapshotHydrator,
        grader_state: GradeSubmitState,
        inputs: GradeInputs,
        **kwargs,
    ):
        """Create compositor with grader dependencies.

        Args:
            snapshot_slug: Snapshot slug to hydrate and mount at /snapshots/<slug>.
            docker_client: Async Docker client (managed by caller).
            hydrator: Snapshot hydrator (parent class handles hydration).
            grader_state: Grader submit state container.
            inputs: Grading context (snapshot slug and critique).
            **kwargs: Additional arguments passed to PropertiesDockerCompositor
                (mount_properties, db_conn, extra_binds, network_mode, extra_env)
                Note: ephemeral is hardcoded to False
        """
        self._snapshot_slug = snapshot_slug
        self._docker_client = docker_client
        self._hydrator = hydrator
        self._grader_state = grader_state
        self._inputs = inputs
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

        # Mount grader submit server
        self.grader_submit = await self.mount_inproc(
            "grader_submit", GraderSubmitServer(self._grader_state, self._inputs), pinned=True
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
    hydrator: SnapshotHydrator,
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
    db_config: DatabaseConfig,
    http_mode: bool = False,
    max_lines: int = DEFAULT_MAX_LINES,
    max_turns: int,
) -> GraderOutput:
    """Run the grader agent.

    Args:
        hydrator: Snapshot hydrator for mounting snapshot source code
        http_mode: If True, grader_submit is exposed via HTTP (managed by PropertiesDockerCompositorHTTP).
            If False, grader_submit is mounted in compositor (which handles snapshot hydration).
        canonical_tps: True positive issues from specimen
        critique_typed: Issues from the critique being graded
        canonical_fps: Known false positives from specimen

    Returns:
        GraderSuccess if completed, GraderMaxTurnsExceeded if agent ran out of turns
    """
    # Choose compositor based on http_mode
    # HTTP mode: use PropertiesDockerCompositorHTTP (manages both HTTP server and container)
    #            Network: PROPS_NETWORK_NAME, workspace: rw, ephemeral: False, db_conn: required
    #            Creates temp workspace and hydrates snapshot source code
    # Inproc mode: use GraderCompositor (runtime + grader_submit mounted in-proc)
    #              Network: "none" (isolated, no network access needed)
    #              Compositor handles temp workspace and snapshot hydration internally
    comp_ctx: PropertiesDockerCompositor
    workspace_tmpdir = None

    try:
        if http_mode:
            # HTTP mode: Create temp workspace and hydrate snapshot manually
            # (PropertiesDockerCompositorHTTP doesn't have built-in hydration like GraderCompositor)
            workspace_tmpdir = tempfile.TemporaryDirectory(prefix="grader_http_workspace_")
            workspace_path = Path(workspace_tmpdir.__enter__())

            # Hydrate snapshot source code to workspace
            async with hydrator.hydrate(input_data.snapshot_slug) as hydrated:
                # Copy snapshot content to workspace
                for item in hydrated.content_root.iterdir():
                    if item.is_dir():
                        shutil.copytree(item, workspace_path / item.name)
                    else:
                        shutil.copy2(item, workspace_path / item.name)

            # Server factory for HTTP compositor
            def server_factory(token: str) -> EnhancedFastMCP:
                auth = StaticTokenVerifier(tokens={token: {"client_id": "grader-agent", "scopes": []}})
                return GraderSubmitServer(grader_state, inputs, auth)

            # Container-to-container database access with admin credentials
            db_conn_container = db_config.admin_for_container

            comp_ctx = PropertiesDockerCompositorHTTP(
                workspace_path,
                docker_client,
                server_factory=server_factory,
                db_conn=db_conn_container,
                mount_properties=False,
            )
        else:
            comp_ctx = GraderCompositor(
                snapshot_slug=input_data.snapshot_slug,
                docker_client=docker_client,
                hydrator=hydrator,
                grader_state=grader_state,
                inputs=inputs,
                mount_properties=False,
                # ephemeral=False is hardcoded in GraderCompositor
                # network_mode defaults to "none" (isolated)
            )

        async with comp_ctx as handle:
            # Build prompt - tool name differs based on mode:
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

            prompt = build_grade_from_json_prompt(submit_tool_name=submit_tool_name, compositor=handle)

            # Note: resources and compositor_meta are auto-mounted by base Compositor
            async with Client(handle) as mcp_client:
                # Build system prompt with MCP HTTP instructions if in http_mode
                if http_mode:
                    system = f"""You are a strict grader evaluating a code critique.

Grade the critique, then submit your result by invoking the MCP server's submit_result tool.

The snapshot slug for this grader run is available at the MCP resource `{GRADER_SNAPSHOT_SLUG_RESOURCE_URI}`.

You do not have direct access to invoke the server's tools - the MCP server is networked to the container that docker_exec runs commands in. To interact with the server (and to submit your work using its submit_result tool), use docker_exec to run a process in the container that will talk to the MCP server over the MCP protocol (Streamable HTTP transport). The server is available at MCP_SERVER_URL with authentication token MCP_SERVER_TOKEN.

Important: MCP sessions must be initialized (session.initialize()) before you can use tools, list resources, etc. When used in one-off Python scripts, the session will be closed at the end of the script.

{GRADER_COMMON_INSTRUCTIONS}

{MCP_HTTP_CONNECTION_INSTRUCTIONS}"""
                else:
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

        print("=== Snapshot Slug ===")
        result = await session.read_resource("{GRADER_SNAPSHOT_SLUG_RESOURCE_URI}")
        print(json.dumps(result.model_dump(mode="json"), indent=2))

        print("=== Canonical True Positives ===")
        result = await session.read_resource("{GRADER_CANONICAL_TPS_RESOURCE_URI}")
        print(json.dumps(result.model_dump(mode="json"), indent=2))

        print("=== Critique Issues ===")
        result = await session.read_resource("{GRADER_CRITIQUE_ISSUES_RESOURCE_URI}")
        print(json.dumps(result.model_dump(mode="json"), indent=2))

        print("=== Known False Positives ===")
        result = await session.read_resource("{GRADER_KNOWN_FPS_RESOURCE_URI}")
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

                handlers_list.extend(
                    [
                        AbortIf(should_abort=lambda: grader_state.result is not None),
                        *await build_props_handlers(
                            transcript_id=transcript_id,
                            verbose_prefix=(
                                f"[GRADER {short_uuid(transcript_id)} {snapshot_split} {input_data.snapshot_slug}] "
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
                except MaxTurnsExceededError:
                    # Agent ran out of turns - create max_turns_exceeded output
                    # NOTE: max_turns_exceeded is taken as recall=0.0 (see query_builders.py:803-806)
                    logger.warning(
                        f"Grader hit max turns limit ({max_turns}) for {input_data.snapshot_slug}, "
                        f"transcript_id={short_uuid(transcript_id)}"
                    )
                    return GraderMaxTurnsExceeded(max_turns=max_turns)

        # Agent completed normally - validate state and return success
        if grader_state.result is None:
            raise GraderDidNotSubmitError("Grader did not submit result")

        return grader_state.result
    finally:
        # Clean up temporary workspace in HTTP mode
        if workspace_tmpdir is not None:
            workspace_tmpdir.__exit__(None, None, None)


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
        input_data: Grader input with snapshot_slug and critique_id
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
                            ranges=(
                                [LineRange(start_line=r.start_line, end_line=r.end_line) for r in fo.ranges]
                                if fo.ranges
                                else None
                            ),
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
        snapshot_slug=input_data.snapshot_slug,
        critique=critique_payload_db,
        canonical_tps=canonical_tps,
        critique_typed=critique_typed,
        canonical_fps=canonical_fps,
        reviewed_files=reviewed_files,
    )

    # Run agent with either HTTP or in-proc server based on toggle
    logger.info(f"HTTP mode enabled: {USE_MCP_HTTP}")
    output = await _run_grader_agent(
        grader_state=grader_state,
        inputs=inputs,
        hydrator=hydrator,
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
        db_config=db_config,
        http_mode=USE_MCP_HTTP,
        max_lines=max_lines,
        max_turns=max_turns,
    )

    # Phase 2: Update run with output
    with get_session() as session:
        found_run = session.get(DBGraderRun, run_id)
        assert found_run is not None, f"Grader run {run_id} not found in database"
        # Convert MCP model (discriminated union) to DB model for storage
        found_run.output = grader_output_to_db(output)
        session.commit()
        logger.info(
            f"Updated grader run in DB: {transcript_id=}, snapshot_slug={input_data.snapshot_slug}, status={output.tag}"
        )

    return run_id


async def grade_critique_by_id(
    session: Session,
    critique_id: UUID,
    client: OpenAIModelProto,
    docker_client: aiodocker.Docker,
    hydrator: SnapshotHydrator,
    db_config: DatabaseConfig,
    prompt_optimization_run_id: UUID | None = None,
    verbose: bool = False,
    max_turns: int = 200,
) -> UUID:
    """Grade critique by ID, return grader_run_id.

    Args:
        session: Database session (caller manages transaction)
        critique_id: ID of critique to grade
        client: OpenAI client
        docker_client: Async Docker client
        hydrator: Snapshot hydrator for mounting snapshot source code
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

    # Filter TPs/FPs by critic scope at ORM level (before conversion)
    if critique.critic_run:
        reviewed_files = {Path(f) for f in critique.critic_run.files}

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
    else:
        # No filtering - convert all ORM models to MCP models
        canonical_tps = [_tp_from_orm(tp) for tp in snapshot.true_positives]
        canonical_fps = [_fp_from_orm(fp) for fp in snapshot.false_positives]

    # Create grader input
    grader_input = GraderInput(
        snapshot_slug=snapshot_slug, critique_id=critique_id, prompt_optimization_run_id=prompt_optimization_run_id
    )

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
