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

import logging
from uuid import UUID, uuid4

import aiodocker
from fastmcp.client import Client
from fastmcp.server.auth import AuthProvider
import typer

from adgn.agent.display import CompactDisplayHandler
from adgn.agent.handler import AbortIf, BaseHandler, RedirectOnTextMessageHandler
from adgn.agent.turn_limit import MaxTurnsExceededError, MaxTurnsHandler
from adgn.mcp.enhanced import EnhancedFastMCP
from adgn.openai_utils.errors import ContextLengthExceededError
from adgn.openai_utils.model import OpenAIModelProto
from adgn.props.agent_handle import AgentHandle, ensure_definition_unpacked
from adgn.props.agent_setup import AgentEnvironment
from adgn.props.agent_types import CriticTypeConfig
from adgn.props.agent_workspace import WorkspaceManager
from adgn.props.cli.common_options import DEFAULT_MAX_LINES
from adgn.props.critic.exceptions import CriticDidNotSubmitError, CriticExecutionError
from adgn.props.critic.submit_server import CriticSubmitServer
from adgn.props.db import get_session
from adgn.props.db.agent_definition_ids import CRITIC_AGENT_DEFINITION_ID
from adgn.props.db.config import DatabaseConfig
from adgn.props.db.models import AgentRun, AgentRunStatus, Snapshot
from adgn.props.display import short_uuid
from adgn.props.hydration import SnapshotHydrator
from adgn.props.models.examples import ExampleSpec

logger = logging.getLogger(__name__)


# =============================================================================
# Critic Agent Environment (HTTP Mode)
# =============================================================================


class CriticAgentEnvironment(AgentEnvironment):
    """Agent environment for HTTP-mode critic with critic_submit tool.

    Provides complete environment for critic agents:
    - Temporary database user with RLS scoping (agent_{run_id})
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
            example=WholeSnapshotExample(snapshot_slug="ducktape/2025-11-26-00"),
            docker_client=docker_client,
            hydrator=hydrator,
            agent_run_id=run_id,
            db_config=db_config,
            workspace_manager=workspace_manager,
        ) as compositor:
            # Run critic agent
            ...
    """

    def __init__(
        self,
        example: ExampleSpec,
        docker_client: aiodocker.Docker,
        hydrator: SnapshotHydrator,
        agent_run_id: UUID,
        db_config: DatabaseConfig,
        workspace_manager: WorkspaceManager,
        *,
        definition_id: str = CRITIC_AGENT_DEFINITION_ID,
        container_name: str | None = None,
    ):
        """Create critic agent environment.

        Args:
            example: Example specification (snapshot + scope)
            docker_client: Async Docker client
            hydrator: Snapshot hydrator
            agent_run_id: UUID of the agent run (for RLS scoping)
            db_config: Database configuration (passed via DI)
            workspace_manager: Workspace manager for agent workspace paths
        """
        # Store params needed by _make_mcp_server (before super().__init__ since it accesses them)
        self._example = example

        name = container_name or f"critic-{definition_id[:12]}-{short_uuid(agent_run_id)}"

        super().__init__(
            definition_id=definition_id,
            agent_run_id=agent_run_id,
            docker_client=docker_client,
            hydrator=hydrator,
            db_config=db_config,
            workspace_manager=workspace_manager,
            snapshot_slugs=[example.snapshot_slug],
            container_name=name,
            labels={
                "adgn.project": "props",
                "adgn.role": "critic",
                "adgn.definition_id": definition_id,
                "adgn.agent_run_id": str(agent_run_id),
            },
            auto_remove=True,
        )

    def _make_mcp_server(self, auth: AuthProvider) -> EnhancedFastMCP:
        """Create critic submit server with hydrated snapshot path.

        Called by PropertiesDockerCompositorHTTP after hydration completes.
        Accesses self._hydrated_paths populated by base class.

        Args:
            auth: Auth provider for HTTP authentication

        Returns:
            CriticSubmitServer configured with actual hydrated host path
        """
        hydrated_path = self._hydrated_paths[self._example.snapshot_slug]
        return CriticSubmitServer(
            agent_run_id=self._agent_run_id,
            snapshot_slug=self._example.snapshot_slug,
            example=self._example,
            snapshot_hydrated_path=hydrated_path,
            auth=auth,
        )


# =============================================================================
# Critic Run (AgentHandle-based)
# =============================================================================


async def run_critic(
    *,
    definition_id: str,
    example: ExampleSpec,
    client: OpenAIModelProto,
    parent_agent_run_id: UUID | None,
    docker_client: aiodocker.Docker,
    hydrator: SnapshotHydrator,
    db_config: DatabaseConfig,
    workspace_manager: WorkspaceManager,
    extra_handlers: tuple[BaseHandler, ...] = (),
    verbose: bool = False,
    max_lines: int = DEFAULT_MAX_LINES,
    max_turns: int,
) -> tuple[UUID, AgentRunStatus]:
    """Execute critic agent using AgentHandle (definition-based).

    Uses AgentHandle to load a critic definition from the database. The definition's
    AGENT.md provides the system prompt (no template rendering).

    The prompt optimizer creates new definitions (e.g., "critic-v1", "critic-v2") with
    evolved AGENT.md content. This function runs any such definition.

    This function creates an AgentRun record. Agent definitions are the source of
    truth for prompt content.

    Args:
        definition_id: Agent definition ID to load (e.g., "critic", "critic-v1")
        example: Example specification (snapshot + scope)
        client: OpenAI-compatible model client
        parent_agent_run_id: Optional parent agent run ID (e.g., prompt optimizer)
        docker_client: Async Docker client
        hydrator: Snapshot hydrator
        db_config: Database configuration
        workspace_manager: Workspace manager for agent workspace paths
        extra_handlers: Additional handlers to add
        verbose: Whether to enable verbose display
        max_lines: Max lines per event in verbose display
        max_turns: Maximum agent turns before timeout

    Returns:
        Tuple of (agent_run_id, status)

    Note:
        - Uses CriticAgentEnvironment for temp user, CriticSubmitServer, hydration
        - Uses AgentHandle for definition loading, AGENT.md system prompt, init script
        - Definition's init script runs bootstrap (prints schema, helpers, scope)
    """
    # Extract snapshot_slug for convenience
    snapshot_slug = example.snapshot_slug

    # Generate unique ID for this run
    agent_run_id = uuid4()

    # Phase 1: Write initial AgentRun to DB (BEFORE agent runs - FK constraint!)
    with get_session() as session:
        # Fetch snapshot to get split for verbose prefix
        snapshot = session.query(Snapshot).filter_by(slug=snapshot_slug).one()
        snapshot_split = snapshot.split

        # Store critic-specific config in type_config JSONB
        type_config = CriticTypeConfig(example=example)

        agent_run = AgentRun(
            agent_run_id=agent_run_id,
            agent_definition_id=definition_id,
            parent_agent_run_id=parent_agent_run_id,
            model=client.model,
            type_config=type_config,
            status=AgentRunStatus.IN_PROGRESS,
        )
        session.add(agent_run)
        session.commit()
        logger.info(f"Created initial agent run in DB: agent_run_id={agent_run_id}, snapshot_slug={snapshot_slug}")
        typer.echo(f"[critic_v2] agent_run_id={short_uuid(agent_run_id)}", err=True)

    # Get workspace path and ensure definition is unpacked BEFORE starting container
    # (Docker mount creates the directory as root if it doesn't exist, preventing unpack)
    workspace_path = workspace_manager.get_path(agent_run_id)
    ensure_definition_unpacked(definition_id, workspace_path)

    # Use CriticAgentEnvironment for:
    # - Temporary database user with RLS scoping
    # - HTTP MCP server with critic_submit tool
    # - Docker container with docker_exec
    # - Hydrated snapshot mounted at /snapshots/<slug>/
    comp_ctx = CriticAgentEnvironment(
        example=example,
        docker_client=docker_client,
        hydrator=hydrator,
        agent_run_id=agent_run_id,
        db_config=db_config,
        workspace_manager=workspace_manager,
    )

    async with comp_ctx as comp, Client(comp) as mcp_client:
        # Build handlers for AgentHandle
        def _ready_state() -> bool:
            with get_session() as session:
                run = session.get(AgentRun, agent_run_id)
                return run is not None and run.status in (AgentRunStatus.COMPLETED, AgentRunStatus.REPORTED_FAILURE)

        # Build handlers for AgentHandle
        # NOTE: Do NOT call build_props_handlers() here - AgentHandle.create() already adds
        # DatabaseEventHandler. We only add CompactDisplayHandler if verbose is enabled.
        handlers: list[BaseHandler] = []
        if verbose:
            display_handler = await CompactDisplayHandler.from_compositor(
                comp,
                max_lines=max_lines,
                prefix=f"[CRITIC_V2 {short_uuid(agent_run_id)} {snapshot_split} {snapshot_slug}] ",
            )
            handlers.append(display_handler)

        handlers.extend(
            [
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
        )

        # Create AgentHandle - this loads definition, unpacks workspace, runs init
        handle = await AgentHandle.create(
            agent_run_id=agent_run_id,
            definition_id=definition_id,
            model_client=client,
            mcp_client=mcp_client,
            compositor=comp,
            workspace_manager=workspace_manager,
            handlers=handlers,
        )

        # Run the agent
        agent_status: AgentRunStatus
        try:
            await handle.run()
        except MaxTurnsExceededError:
            logger.warning(
                f"Critic hit max turns limit ({max_turns}) for {snapshot_slug}, agent_run_id={short_uuid(agent_run_id)}"
            )
            agent_status = AgentRunStatus.MAX_TURNS_EXCEEDED
        except ContextLengthExceededError as e:
            logger.warning(
                f"Critic hit context length limit for {snapshot_slug}, agent_run_id={short_uuid(agent_run_id)}: {e}"
            )
            agent_status = AgentRunStatus.CONTEXT_LENGTH_EXCEEDED
        else:
            # Agent completed normally - check database
            with get_session() as session:
                run = session.get(AgentRun, agent_run_id)
                if run is None:
                    raise CriticExecutionError("Agent run not found in database")

                if run.status == AgentRunStatus.REPORTED_FAILURE:
                    raise CriticExecutionError(f"Critic reported failure: {run.completion_summary or 'No message'}")

                if run.status != AgentRunStatus.COMPLETED:
                    raise CriticDidNotSubmitError("Critic did not submit")

                agent_status = AgentRunStatus.COMPLETED

    # Phase 2: Update run with status
    with get_session() as session:
        found_run = session.get(AgentRun, agent_run_id)
        assert found_run is not None, f"Agent run {agent_run_id} not found in database"

        found_run.status = agent_status
        session.commit()

        result_id = found_run.agent_run_id
        logger.info(f"Updated agent run in DB: agent_run_id={agent_run_id}, snapshot_slug={snapshot_slug}")

    return (result_id, agent_status)
