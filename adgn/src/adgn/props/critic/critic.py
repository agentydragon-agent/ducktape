"""Critic MCP server and CriticSubmitPayload models.

This module defines the strict structured output used by the critic agent (codebase → candidate issues)
and a tiny FastMCP server that accepts exactly one submission per run via ``submit``.

Candidate issues are expressed as IssueCore + Occurrence(s); freeform notes allowed only via notes_md.
Payload is validated with Pydantic.

Critic agent MUST call ``submit(issues_count)`` after building the critique using the incremental tools.

TODO: Enable compaction for critic runs to reduce transcript size.
TODO: Do not install adgn package into critic container - snapshots contain past versions of adgn
      and installing current adgn would create conflicts/pollution in the review environment.
"""

from collections.abc import Sequence
import logging
from pathlib import Path
import tempfile
from uuid import UUID, uuid4

import aiodocker
from fastmcp.client import Client
from fastmcp.server.auth import AuthProvider
import typer

from adgn.agent.agent import Agent
from adgn.agent.bootstrap import TypedBootstrapBuilder, docker_exec_call_mounted
from adgn.agent.handler import AbortIf, BaseHandler, RedirectOnTextMessageHandler, SequenceHandler
from adgn.agent.loop_control import AllowAnyToolOrTextMessage, InjectItems
from adgn.agent.turn_limit import MaxTurnsExceededError, MaxTurnsHandler
from adgn.mcp.enhanced import EnhancedFastMCP
from adgn.openai_utils.model import OpenAIModelProto
from adgn.openai_utils.types import ReasoningSummary
from adgn.props.agent_setup import AgentEnvironment, build_props_handlers
from adgn.props.cli.common_options import DEFAULT_MAX_LINES
from adgn.props.critic.exceptions import CriticDidNotSubmitError, CriticExecutionError
from adgn.props.critic.models import CriticInput, CriticScopeSpec, ResolvedFileScope
from adgn.props.critic.submit_server import (
    CRITIC_SCOPE_RESOURCE_URI,
    CRITIC_SNAPSHOT_SLUG_RESOURCE_URI,
    SUBMIT_PREFIX,
    CriticSubmitServer,
)
from adgn.props.critic.user_manager import CriticUserManager
from adgn.props.db import get_session
from adgn.props.db.config import DatabaseConfig
from adgn.props.db.examples import Example
from adgn.props.db.models import CriticRun as DBCriticRun, CriticRunStatus, Prompt, Snapshot

# DB output types no longer used - status is in enum column, semantic data in normalized tables
from adgn.props.display import short_uuid
from adgn.props.docker_env import PropertiesDockerCompositor
from adgn.props.hydration import SnapshotHydrator
from adgn.props.ids import SnapshotSlug
from adgn.props.lint_issue import make_bootstrap_calls_for_inspection
from adgn.props.models.critic_scopes import AllFilesScope, ExplicitFileScope
from adgn.props.prompts.util import render_prompt_template

logger = logging.getLogger(__name__)


# =============================================================================
# Critic Scope Resolution
# =============================================================================


async def resolve_critic_scope(snapshot_slug: SnapshotSlug, files: CriticScopeSpec) -> ResolvedFileScope:
    """Resolve file scope for critic, handling discriminated union.

    Loads files with issues from database (no jsonnet evaluation).

    Args:
        snapshot_slug: Target snapshot
        files: Discriminated union of ExplicitFileScope or AllFilesScope

    Returns:
        Resolved file set (guaranteed non-empty)

    Raises:
        ValueError: If AllFilesScope is used but snapshot has no files with issues
    """
    resolved_files: set[Path]
    if isinstance(files, AllFilesScope):
        # Load files with issues from database (not from jsonnet!)
        with get_session() as session:
            snapshot = session.query(Snapshot).filter_by(slug=snapshot_slug).one()
            resolved_files = snapshot.files_with_issues()
            if not resolved_files:
                raise ValueError(
                    f"Snapshot '{snapshot_slug}' has no files with ground truth issues. "
                    "Cannot use AllFilesScope sentinel."
                )
    else:
        # Type narrowing: must be ExplicitFileScope
        assert isinstance(files, ExplicitFileScope)
        resolved_files = {Path(f) for f in files.files}

    return resolved_files


# =============================================================================
# Critic Agent Environment (HTTP Mode)
# =============================================================================


class CriticAgentEnvironment(AgentEnvironment):
    """Agent environment for HTTP-mode critic with critic_submit tool.

    Provides complete environment for critic agents:
    - Temporary database user with RLS scoping (critic_agent_{run_id})
    - HTTP MCP server with critic_submit tool
    - Docker container with docker_exec
    - Hydrated snapshot mounted at /snapshots/<slug>/

    Agent workflow:
    1. Reviews code at /snapshots/<slug>/
    2. Writes reported issues directly to PostgreSQL
    3. Calls critic_submit tool via MCP-over-HTTP when done
    4. Submit validates decisions and marks run complete

    Usage:
        async with CriticAgentEnvironment(
            snapshot_slug="ducktape/2025-11-26-00",
            docker_client=docker_client,
            hydrator=hydrator,
            critic_run_id=run_id,
            scope=input_data.scope,
            mount_properties=True,
        ) as compositor:
            # Run critic agent
            ...
    """

    def __init__(
        self,
        snapshot_slug: SnapshotSlug,
        docker_client: aiodocker.Docker,
        hydrator: SnapshotHydrator,
        critic_run_id: UUID,
        scope: CriticScopeSpec,
        db_config: DatabaseConfig,
        mount_properties: bool = False,
    ):
        """Create critic agent environment.

        Args:
            snapshot_slug: Snapshot slug to hydrate and mount
            docker_client: Async Docker client
            hydrator: Snapshot hydrator
            critic_run_id: UUID of the critic run (for RLS scoping)
            scope: Critic scope specification (AllFilesScope or ExplicitFileScope)
            db_config: Database configuration (passed via DI)
            mount_properties: Whether to mount property definitions at /props
        """

        def make_user_manager() -> CriticUserManager:
            """Create temporary critic user with RLS scoping."""
            return CriticUserManager(db_config.admin, critic_run_id)

        def make_mcp_server(auth: AuthProvider) -> EnhancedFastMCP:
            """Create critic submit server (auth provided by HTTP server)."""
            return CriticSubmitServer(
                critic_run_id=critic_run_id,
                snapshot_slug=snapshot_slug,
                scope=scope,
                auth=auth,
                incremental_tools=False,  # Agent writes SQL directly
            )

        super().__init__(
            docker_client=docker_client,
            user_manager_factory=make_user_manager,
            mcp_server_factory=make_mcp_server,
            hydrator=hydrator,
            snapshot_slugs=[snapshot_slug],
            workspace_prefix="critic_workspace_",
            mount_properties=mount_properties,
        )

    def bootstrap_mcp_resources(self) -> Sequence[tuple[str, str]]:
        """Return MCP resources to read during bootstrap: snapshot slug and scope."""
        return [("Snapshot Slug", CRITIC_SNAPSHOT_SLUG_RESOURCE_URI), ("Scope", CRITIC_SCOPE_RESOURCE_URI)]


# =============================================================================
# Critic Run Function
# =============================================================================


async def run_critic(
    *,
    input_data: CriticInput,
    client: OpenAIModelProto,
    prompt_optimization_run_id: UUID | None,
    docker_client: aiodocker.Docker,
    hydrator,
    db_config: DatabaseConfig,
    mount_properties: bool = False,
    extra_handlers: tuple[BaseHandler, ...] = (),
    verbose: bool = False,
    max_lines: int = DEFAULT_MAX_LINES,
    max_turns: int,
    http_mode: bool = False,
) -> tuple[UUID, CriticRunStatus]:
    """Execute critic agent to produce candidate issues and persist to DB.

    Sets up critic submit server, Docker exec MCP, and standard handlers (bootstrap,
    database events, AbortIf). Runs agent until submit_result or error is called.

    Args:
        http_mode: If True, critic_submit is exposed via HTTP (managed by CriticAgentEnvironment).
            If False, critic_submit is mounted in compositor (which handles snapshot hydration).

    Returns:
        Tuple of (critic_run_id, status)
        - critic_run_id: UUID of the critic run record
        - status: CriticRunStatus indicating completion state

    Note: Returns IDs only (not ORM objects) to avoid DetachedInstanceError when called
    from within an MCP tool that outlives the session. Callers needing full data should
    query the database using the returned critic_run_id.
    """
    # Fetch optimized prompt from DB using prompt_sha256 (primary key lookup)
    with get_session() as session:
        prompt_obj = session.get(Prompt, input_data.prompt_sha256)
        if not prompt_obj:
            raise ValueError(f"Prompt not found in database: {input_data.prompt_sha256}")
        optimized_prompt = prompt_obj.prompt_text

    # Compute scope hash for content-addressed example lookup
    scope_hash = Example.from_scope(input_data.snapshot_slug, input_data.scope).scope_hash

    # Generate unique IDs for this run
    run_id = uuid4()
    transcript_id = uuid4()

    # Phase 1: Write initial run to DB (BEFORE agent runs - FK constraint!)
    with get_session() as session:
        # Fetch snapshot to get split for verbose prefix
        snapshot = session.query(Snapshot).filter_by(slug=input_data.snapshot_slug).one()
        snapshot_split = snapshot.split

        db_run = DBCriticRun(
            id=run_id,
            transcript_id=transcript_id,
            prompt_sha256=input_data.prompt_sha256,
            snapshot_slug=input_data.snapshot_slug,
            scope_hash=scope_hash,
            model=client.model,
            prompt_optimization_run_id=prompt_optimization_run_id,
            # output is nullable, will be set by submit server
        )
        session.add(db_run)
        session.commit()
        logger.info(
            f"Created initial critic run in DB: {run_id=}, {transcript_id=}, snapshot_slug={input_data.snapshot_slug}"
        )
        # Print IDs early to console for easy retrieval if run is interrupted
        typer.echo(f"[critic] transcript_id={short_uuid(transcript_id)} run_id={short_uuid(run_id)}", err=True)

    # Choose compositor based on http_mode
    # HTTP mode: use CriticAgentEnvironment (manages user, HTTP server, and container)
    #            Network: PROPS_NETWORK_NAME, snapshots mounted at /snapshots/<slug>/
    #            Server: incremental_tools=False (agent writes SQL directly, only submit/report_failure)
    # In-proc mode: use PropertiesDockerCompositor (runtime + critic_submit mounted in-proc)
    #               Network: "none" (isolated, no network access needed)
    #               Creates temp workspace and hydrates snapshot internally
    #               Server: incremental_tools=True (MCP tools write to PostgreSQL)
    comp_ctx: CriticAgentEnvironment | PropertiesDockerCompositor
    workspace_tmpdir = None  # Only for in-proc mode
    critic_submit_server: EnhancedFastMCP | None = None

    try:
        if http_mode:
            # HTTP mode: Use CriticAgentEnvironment (manages user, HTTP server, container)
            comp_ctx = CriticAgentEnvironment(
                snapshot_slug=input_data.snapshot_slug,
                docker_client=docker_client,
                hydrator=hydrator,
                critic_run_id=run_id,
                scope=input_data.scope,
                db_config=db_config,
                mount_properties=mount_properties,
            )
        else:
            # In-proc mode: Create temp workspace manually
            workspace_tmpdir = tempfile.TemporaryDirectory(prefix="critic_inproc_workspace_")
            workspace_path = Path(workspace_tmpdir.__enter__())

            # Create unified critic submit server with incremental tools (writes to PostgreSQL)
            critic_submit_server = CriticSubmitServer(
                critic_run_id=run_id,
                snapshot_slug=input_data.snapshot_slug,
                scope=input_data.scope,
                incremental_tools=True,
            )

            comp_ctx = PropertiesDockerCompositor(
                workspace_path,
                docker_client,
                hydrator=hydrator,
                snapshot_slugs=[input_data.snapshot_slug],
                workspace_mode="rw",
                ephemeral=False,  # Critic needs persistent workspace
                mount_properties=mount_properties,
                network_mode="none",  # Isolated, no network access
            )

        async with comp_ctx as comp:
            # Mount critic submit server in in-proc mode
            if not http_mode and critic_submit_server is not None:
                critic_submit_mount = await comp.mount_inproc(SUBMIT_PREFIX, critic_submit_server, pinned=True)

            # Set up handlers
            builder = TypedBootstrapBuilder.for_server(comp.runtime.server)

            # Build bootstrap: different for HTTP vs in-proc mode
            if http_mode:
                # HTTP mode: Use agent environment's bootstrap method
                logger.info("Critic bootstrap: using agent environment bootstrap items")
                # Type narrowing: comp_ctx is CriticAgentEnvironment in HTTP mode
                assert isinstance(comp_ctx, CriticAgentEnvironment), "HTTP mode requires CriticAgentEnvironment"
                bootstrap_calls = comp_ctx.bootstrap_items(builder, comp.runtime)
            else:
                # In-proc mode: Direct resource reads via compositor
                snapshot_path = comp.snapshot_container_path(input_data.snapshot_slug)
                bootstrap_calls = [
                    *make_bootstrap_calls_for_inspection(comp, builder),
                    # Show snapshot directory structure
                    docker_exec_call_mounted(builder, comp.runtime, cmd=["ls", "-la", str(snapshot_path)]),
                    # Read snapshot slug from critic_submit server resource
                    builder.read_resource(
                        comp.resources,
                        server=critic_submit_mount.prefix,
                        uri=CRITIC_SNAPSHOT_SLUG_RESOURCE_URI,
                        max_bytes=256,
                    ),
                    # Read file scope from critic_submit server resource
                    builder.read_resource(
                        comp.resources,
                        server=critic_submit_mount.prefix,
                        uri=CRITIC_SCOPE_RESOURCE_URI,
                        max_bytes=65536,
                    ),
                ]

            bootstrap = SequenceHandler([InjectItems(items=bootstrap_calls)])

            def _ready_state() -> bool:
                # Both HTTP and in-proc modes now write to database (unified server with incremental_tools)
                with get_session() as session:
                    critic_run = session.get(DBCriticRun, run_id)
                    return critic_run is not None and critic_run.status in (
                        CriticRunStatus.COMPLETED,
                        CriticRunStatus.REPORTED_FAILURE,
                    )

            handlers: list = [
                bootstrap,
                *await build_props_handlers(
                    transcript_id=transcript_id,
                    verbose_prefix=f"[CRITIC {short_uuid(transcript_id)} {snapshot_split} {input_data.snapshot_slug}] "
                    if verbose
                    else None,
                    compositor=comp,
                    max_lines=max_lines,
                ),
                RedirectOnTextMessageHandler(
                    reminder_message=(
                        "You are a code review critic agent. The critique has not yet been submitted "
                        "(critique_submit tool has not been called), so your task is unfinished. "
                        "Use the provided MCP tools to mark all issues and occurrences you want to report, "
                        "then either submit the critique or report failure if you encounter unrecoverable problems. "
                        "This is not an interactive workflow with a user - issues must be reported via MCP tools, "
                        "not via text messages. Once all issues are marked, submit the critique via the MCP tool."
                    )
                ),
                AbortIf(should_abort=_ready_state),
                *extra_handlers,
                MaxTurnsHandler(max_turns=max_turns),
            ]

            # Build combined dynamic instructions by rendering the template
            async def _build_critic_instructions() -> str:
                """Build critic system instructions by rendering critic_system.j2.md template.

                The template has two placeholders:
                1. {{ compositor_instructions }} - MCP wiring: servers, tools, resources
                2. {{ optimized_prompt }} - The prompt being tested/optimized
                """
                compositor_instructions = comp.render_agent_dynamic_instructions()
                return render_prompt_template(
                    "critic/prompts/critic_system.j2.md",
                    compositor_instructions=compositor_instructions,
                    optimized_prompt=optimized_prompt,
                )

            # Run critic agent
            # Note: resources and compositor_meta are auto-mounted by base Compositor
            async with Client(comp) as mcp_client:
                agent = await Agent.create(
                    mcp_client=mcp_client,
                    client=client,
                    handlers=handlers,
                    parallel_tool_calls=True,
                    tool_policy=AllowAnyToolOrTextMessage(),
                    reasoning_summary=ReasoningSummary.detailed,
                    dynamic_instructions=_build_critic_instructions,
                )
                status: CriticRunStatus
                try:
                    await agent.run()
                except MaxTurnsExceededError:
                    # Agent ran out of turns
                    # NOTE: max_turns_exceeded is taken as recall=0.0 (see query_builders.py:803-806)
                    logger.warning(
                        f"Critic hit max turns limit ({max_turns}) for {input_data.snapshot_slug}, "
                        f"transcript_id={short_uuid(transcript_id)}"
                    )
                    status = CriticRunStatus.MAX_TURNS_EXCEEDED
                except Exception as e:
                    # Check if this is a context length exceeded error
                    # TODO: Check specifically for openai.BadRequestError with code='context_length_exceeded'
                    # instead of string matching - more robust for different API providers
                    error_str = str(e).lower()
                    if "context_length_exceeded" in error_str or "context window" in error_str:
                        # NOTE: context_length_exceeded is taken as recall=0.0 (see query_builders.py:803-806)
                        logger.warning(
                            f"Critic hit context length limit for {input_data.snapshot_slug}, "
                            f"transcript_id={short_uuid(transcript_id)}: {e}"
                        )
                        status = CriticRunStatus.CONTEXT_LENGTH_EXCEEDED
                    else:
                        # Re-raise other exceptions
                        raise
                else:
                    # Agent completed normally - check database for both HTTP and in-proc modes
                    with get_session() as session:
                        critic_run = session.get(DBCriticRun, run_id)
                        if critic_run is None:
                            raise CriticExecutionError("Critic run not found in database")

                        if critic_run.status == CriticRunStatus.REPORTED_FAILURE:
                            raise CriticExecutionError(
                                f"Critic reported failure: {critic_run.completion_summary or 'No message'}"
                            )

                        if critic_run.status != CriticRunStatus.COMPLETED:
                            raise CriticDidNotSubmitError("Critic did not submit")

                        status = CriticRunStatus.COMPLETED
    # Compositor.__aexit__ unmounts all non-pinned servers and cleans up containers here
    finally:
        # Cleanup in-proc mode resources (HTTP mode cleanup handled by CriticAgentEnvironment)
        if not http_mode and workspace_tmpdir:
            workspace_tmpdir.__exit__(None, None, None)

    # Phase 2: Update run with status
    with get_session() as session:
        # Update run with status
        # Issues are stored in normalized reported_issues table
        found_run = session.get(DBCriticRun, run_id)
        assert found_run is not None, f"Critic run {run_id} not found in database"

        found_run.status = status
        session.commit()

        # Extract ID before session closes (never return ORM objects from functions)
        result_id = found_run.id
        logger.info(f"Updated critic run in DB: {transcript_id=}, snapshot_slug={input_data.snapshot_slug}")

    # Return plain ID and status (SQLAlchemy best practice: never return ORM objects from
    # functions that manage their own sessions - they become detached and cause errors)
    return (result_id, status)
