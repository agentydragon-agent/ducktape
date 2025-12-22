"""Shared utilities for setting up agent workflows in props evaluation.

Agent environments manage the complete lifecycle for agents that:
- Execute commands via docker_exec in a container
- Access database via scoped temporary credentials
- Call submit tools via MCP-over-HTTP
- Use agent definitions (AGENT.md + init script)

Subclasses configure:
- definition_id: Which agent definition to use
- agent_run_id: UUID for this run (workspace path, RLS scoping)
- MCP server factory (provides agent-specific tools)
- Snapshot slugs to hydrate

The base class handles:
- Definition unpacking to workspace (before container starts)
- Temporary database user lifecycle
- HTTP MCP server startup/shutdown
- Docker container with docker_exec tool
- Init script execution via BootstrapHandler (when using AgentHandle)
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from contextlib import AsyncExitStack, suppress
import logging
from pathlib import Path
import secrets
from typing import TYPE_CHECKING
from uuid import UUID

from fastmcp import FastMCP
from fastmcp.server.auth import StaticTokenVerifier
import uvicorn

from adgn.agent.db_event_handler import DatabaseEventHandler
from adgn.agent.display import CompactDisplayHandler
from adgn.agent.handler import BaseHandler
from adgn.mcp._shared.container_session import BindMount
from adgn.mcp.compositor.server import Compositor
from adgn.props.agent_handle import ensure_definition_unpacked
from adgn.props.agent_workspace import WorkspaceManager
from adgn.props.cli.common_options import DEFAULT_MAX_LINES
from adgn.props.db.config import DatabaseConfig
from adgn.props.db.temp_user_manager import TempUserManager
from adgn.props.docker_env import (
    DOCKER_MOUNT_PREFIX,
    PROPS_NETWORK_NAME,
    PropertiesDockerCompositor,
    ensure_critic_image_async,
    get_docker_network_gateway_async,
)
from adgn.props.hydration import SnapshotHydrator
from adgn.props.ids import SnapshotSlug
from adgn.util.net import pick_free_port, wait_for_port

if TYPE_CHECKING:
    import aiodocker
    from fastmcp.server.auth import AuthProvider

logger = logging.getLogger(__name__)


# --- Agent Handlers ---


async def build_props_handlers(
    *, agent_run_id: UUID, verbose_prefix: str | None, compositor: Compositor, max_lines: int = DEFAULT_MAX_LINES
) -> list[BaseHandler]:
    """Build standard handlers for props agent workflows.

    # TODO: Refactor display config threading. Currently `verbose` and `max_lines` are passed
    # separately from CLI through run_critic/run_grader, while `verbose_prefix` is constructed
    # mid-way from internal context (agent_run_id, snapshot_slug, etc.). Consider consolidating
    # into a single `DisplayConfig | None` param constructed at the same level as the prefix,
    # with CLI just passing `max_lines: int | None` (None = no display).

    Always includes DatabaseEventHandler for event persistence.
    Conditionally includes CompactDisplayHandler if verbose_prefix is provided.

    Args:
        agent_run_id: Agent run ID for database event tracking
        verbose_prefix: Optional prefix for verbose display (e.g., "[CRITIC snapshot-slug] ").
                       If None, no verbose handler is added.
        compositor: Compositor instance for extracting server schemas
        max_lines: Max lines per event in verbose display (default from common_options)
    """
    handlers: list[BaseHandler] = [DatabaseEventHandler(agent_run_id=agent_run_id)]

    if verbose_prefix is not None:
        display_handler = await CompactDisplayHandler.from_compositor(
            compositor, max_lines=max_lines, prefix=verbose_prefix
        )
        handlers.append(display_handler)

    return handlers


class AgentEnvironment:
    """Base class for definition-based agent environments with HTTP MCP server.

    Manages complete agent lifecycle:
    1. Unpacks agent definition to workspace (BEFORE container starts)
    2. Creates temporary database user with scoped access
    3. Starts HTTP MCP server with agent-specific tools (via _make_mcp_server)
    4. Creates Docker container with:
       - docker_exec tool available
       - Unpacked definition mounted at /workspace
       - Hydrated snapshots mounted at /snapshots/<slug>/
       - Database credentials in PG* env vars
       - MCP server URL/token in env vars
    5. Cleans up in reverse order on exit

    Agent definition structure (in workspace):
    - AGENT.md: System prompt (loaded by AgentHandle)
    - init: Bootstrap script executed before agent sampling
    - docs/: Reference documentation
    - examples/: Example code

    Subclasses must implement:
    - _make_mcp_server(auth): Create agent-specific MCP server

    Example subclass:
        class CriticAgentEnvironment(AgentEnvironment):
            def __init__(self, snapshot_slug, docker_client, hydrator, agent_run_id,
                         db_config, workspace_manager):
                super().__init__(
                    definition_id="critic",
                    agent_run_id=agent_run_id,
                    docker_client=docker_client,
                    hydrator=hydrator,
                    db_config=db_config,
                    workspace_manager=workspace_manager,
                    snapshot_slugs=[snapshot_slug],
                )

            def _make_mcp_server(self, auth) -> FastMCP:
                return CriticSubmitServer(...)

    Usage:
        async with CriticAgentEnvironment(...) as compositor:
            # Use AgentHandle.create() to run agent with init script
            handle = await AgentHandle.create(
                agent_run_id=agent_run_id,
                definition_id=definition_id,
                compositor=compositor,
                ...
            )
            await handle.run()
    """

    def __init__(
        self,
        definition_id: str,
        agent_run_id: UUID,
        docker_client: aiodocker.Docker,
        hydrator: SnapshotHydrator,
        db_config: DatabaseConfig,
        workspace_manager: WorkspaceManager,
        *,
        snapshot_slugs: Sequence[SnapshotSlug] = (),
    ):
        """Create agent environment.

        Args:
            definition_id: Agent definition ID (e.g., "critic", "grader")
            agent_run_id: UUID for this agent run (used for workspace path and RLS scoping)
            docker_client: Async Docker client (managed by caller)
            hydrator: Snapshot hydrator for loading specimen code
            db_config: Database configuration (includes correct database name for test isolation)
            workspace_manager: Workspace manager for definition unpacking (passed via DI)
            snapshot_slugs: Snapshots to hydrate and mount at /snapshots/<slug>/
        """
        self._definition_id = definition_id
        self._agent_run_id = agent_run_id
        self._docker_client = docker_client
        self._hydrator = hydrator
        self._db_config = db_config
        self._snapshot_slugs = snapshot_slugs
        self._workspace_manager = workspace_manager

        # Unpack definition BEFORE container starts
        ensure_definition_unpacked(definition_id, self.workspace_root)

        # Managed resources (created in __aenter__, cleaned up in __aexit__)
        self._user_manager: TempUserManager | None = None
        self._exit_stack: AsyncExitStack | None = None
        self._snapshot_stack: AsyncExitStack | None = None
        self._compositor: PropertiesDockerCompositor | None = None
        self._hydrated_paths: dict[SnapshotSlug, Path] = {}

    @property
    def definition_id(self) -> str:
        """Agent definition ID."""
        return self._definition_id

    @property
    def agent_run_id(self) -> UUID:
        """Agent run ID."""
        return self._agent_run_id

    @property
    def workspace_root(self) -> Path:
        """Path to unpacked definition workspace."""
        return self._workspace_manager.get_path(self._agent_run_id)

    @property
    def workspace_manager(self) -> WorkspaceManager:
        """Workspace manager for this environment."""
        return self._workspace_manager

    def _make_mcp_server(self, auth: AuthProvider) -> FastMCP:
        """Create MCP server for this agent.

        Subclasses override to provide agent-specific MCP servers.
        Can access self._hydrated_paths populated after compositor __aenter__.

        Args:
            auth: Auth provider for HTTP authentication

        Returns:
            FastMCP server instance
        """
        raise NotImplementedError("Subclasses must implement _make_mcp_server")

    async def __aenter__(self) -> PropertiesDockerCompositor:
        """Start agent environment: user, HTTP server, container.

        Orchestrates the following order:
        1. Create temporary database user with scoped access
        2. Mount resources/compositor_meta (Compositor base)
        3. Hydrate snapshots (populate _hydrated_paths)
        4. Start MCP HTTP server (needs hydrated paths)
        5. Set container environment with MCP server URL/token
        6. Create Docker exec server (uses environment)

        Returns:
            PropertiesDockerCompositor with docker_exec tool available
        """
        logger.info(f"Using workspace: {self.workspace_root}")

        # Create temporary database user with scoped access
        self._user_manager = TempUserManager(self._db_config.admin, self._agent_run_id)
        temp_creds = await self._user_manager.__aenter__()

        logger.info(f"Created temporary database user: {temp_creds.username}")

        # Get container DB config with temp user credentials (use injected config, not environment)
        container_db = self._db_config.for_container_user(temp_creds)

        # Initialize exit stack for HTTP server lifecycle
        self._exit_stack = AsyncExitStack()
        await self._exit_stack.__aenter__()

        # Compute gateway IP for the props network (async)
        container_host = await get_docker_network_gateway_async(self._docker_client, PROPS_NETWORK_NAME)

        # Create base compositor (inheriting from PropertiesDockerCompositor but not using its __aenter__)
        # We manually orchestrate the steps to inject HTTP server between hydration and Docker server creation
        compositor = _AgentDockerCompositor(
            workspace_root=self.workspace_root,
            docker_client=self._docker_client,
            hydrator=self._hydrator,
            snapshot_slugs=self._snapshot_slugs,
            db_conn=container_db,
        )
        self._compositor = compositor

        # Step 1: Mount resources and compositor_meta (call grandparent Compositor.__aenter__)
        await Compositor.__aenter__(compositor)

        # Step 2: Hydrate snapshots
        if self._hydrator and self._snapshot_slugs:
            self._snapshot_stack = AsyncExitStack()
            await self._snapshot_stack.__aenter__()

            extra_snapshot_binds: list[BindMount] = []
            for slug in self._snapshot_slugs:
                hydrated = await self._snapshot_stack.enter_async_context(self._hydrator.hydrate(slug))
                bind = BindMount(
                    host_path=hydrated.content_root.resolve(),
                    container_path=compositor.snapshot_container_path(slug),
                    mode="ro",
                )
                extra_snapshot_binds.append(bind)
                self._hydrated_paths[slug] = bind.host_path
                logger.debug(f"Hydrated {slug} → {hydrated.content_root} (mount as {bind.container_path})")

            compositor._extra_binds = [*compositor._extra_binds, *extra_snapshot_binds]
            logger.info(f"Mounted {len(extra_snapshot_binds)} snapshots (read-only)")

        # Step 3: Start MCP HTTP server (needs hydrated paths for _make_mcp_server)
        token = secrets.token_hex(32)
        auth = StaticTokenVerifier({token: {"client_id": "mcp_agent", "scopes": []}})
        port = pick_free_port(host="127.0.0.1")
        server = self._make_mcp_server(auth)
        app = server.http_app(transport="streamable-http")
        config = uvicorn.Config(app=app, host="0.0.0.0", port=port, log_level="warning", access_log=False)
        uv_server = uvicorn.Server(config)
        server_task = asyncio.create_task(uv_server.serve())

        # Register cleanup for HTTP server
        async def _shutdown_http_server():
            uv_server.should_exit = True
            try:
                await asyncio.wait_for(server_task, timeout=5.0)
            except TimeoutError:
                logger.warning("Server shutdown timed out, cancelling")
                server_task.cancel()
                with suppress(asyncio.CancelledError):
                    await server_task
            except asyncio.CancelledError:
                pass
            logger.info(f"MCP HTTP server on port {port} shut down")

        self._exit_stack.push_async_callback(lambda: _shutdown_http_server())

        # Wait for server to start
        await asyncio.to_thread(wait_for_port, "127.0.0.1", port, timeout_secs=10.0)
        url = f"http://{container_host}:{port}/mcp"
        logger.info(f"MCP HTTP server started at {url}")

        # Step 4: Set container environment with MCP server credentials
        # Note: Agent run ID is available via current_agent_run_id() which extracts
        # it from the database username pattern (agent_{uuid})
        compositor._extra_env = {"MCP_SERVER_URL": url, "MCP_SERVER_TOKEN": token}

        # Step 5: Create Docker exec server
        image_id = await ensure_critic_image_async(self._docker_client)
        docker_server = compositor._create_docker_server(image_id)
        compositor.runtime = await compositor.mount_inproc(DOCKER_MOUNT_PREFIX, docker_server, pinned=True)

        logger.info(f"Started agent environment with {len(self._snapshot_slugs)} snapshot(s)")

        return compositor

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Clean up agent environment: HTTP server, compositor, user (reverse order)."""
        logger.info("AgentEnvironment.__aexit__: starting cleanup")

        try:
            # Clean up exit stack (HTTP server)
            if self._exit_stack:
                logger.info("AgentEnvironment.__aexit__: cleaning up HTTP server")
                await self._exit_stack.__aexit__(exc_type, exc_val, exc_tb)
                self._exit_stack = None

            # Clean up hydrated snapshots
            if self._snapshot_stack is not None:
                logger.info("AgentEnvironment.__aexit__: cleaning up snapshots")
                await self._snapshot_stack.__aexit__(exc_type, exc_val, exc_tb)
                self._snapshot_stack = None

            # Clean up compositor (Compositor base class)
            if self._compositor is not None:
                logger.info("AgentEnvironment.__aexit__: cleaning up compositor")
                await Compositor.__aexit__(self._compositor, exc_type, exc_val, exc_tb)
                self._compositor = None

        finally:
            # Clean up temporary database user (always, even on error)
            if self._user_manager is not None:
                logger.info("AgentEnvironment.__aexit__: cleaning up temp user")
                await self._user_manager.__aexit__(exc_type, exc_val, exc_tb)
                self._user_manager = None

        logger.info("AgentEnvironment.__aexit__: cleanup complete")


class _AgentDockerCompositor(PropertiesDockerCompositor):
    """Internal compositor used by AgentEnvironment.

    This is a simplified version that doesn't run its own __aenter__/__aexit__.
    AgentEnvironment manually orchestrates the lifecycle to inject HTTP server setup
    between hydration and Docker server creation.
    """

    def __init__(
        self,
        workspace_root: Path,
        docker_client: aiodocker.Docker,
        hydrator: SnapshotHydrator,
        snapshot_slugs: Sequence[SnapshotSlug],
        db_conn,
    ):
        super().__init__(
            workspace_root,
            docker_client,
            mount_properties=False,  # Props are in agent definition, not separate mount
            hydrator=hydrator,
            snapshot_slugs=snapshot_slugs,
            db_conn=db_conn,
            workspace_mode="rw",  # HTTP mode always RW
            network_mode=PROPS_NETWORK_NAME,  # Must allow container→host communication
            extra_env=None,  # Will be set by AgentEnvironment after HTTP server starts
            ephemeral=False,  # HTTP mode always persistent
        )
