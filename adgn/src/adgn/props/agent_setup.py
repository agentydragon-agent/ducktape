"""Shared utilities for setting up agent workflows in props evaluation.

Agent environments manage the complete lifecycle for agents that:
- Execute commands via docker_exec in a container
- Access database via scoped temporary credentials
- Call submit tools via MCP-over-HTTP

Subclasses configure:
- User manager factory (creates scoped DB user)
- MCP server factory (provides agent-specific tools)
- Snapshot slugs to hydrate
- Workspace prefix

The base class handles:
- Temporary workspace creation/cleanup
- Temporary database user lifecycle
- HTTP MCP server startup/shutdown
- Docker container with docker_exec tool
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
import logging
from pathlib import Path
import tempfile
from typing import TYPE_CHECKING
from uuid import UUID

from adgn.agent.db_event_handler import DatabaseEventHandler
from adgn.agent.display import CompactDisplayHandler
from adgn.agent.handler import BaseHandler
from adgn.props.cli.common_options import DEFAULT_MAX_LINES
from adgn.props.db.config import get_database_config
from adgn.props.docker_env import PropertiesDockerCompositor
from adgn.props.http_compositor import PropertiesDockerCompositorHTTP
from adgn.props.hydration import SnapshotHydrator
from adgn.props.ids import SnapshotSlug

if TYPE_CHECKING:
    import aiodocker
    from fastmcp import FastMCP
    from fastmcp.server.auth import AuthProvider

    from adgn.mcp.compositor.server import Compositor
    from adgn.props.db.temp_user_manager import TempUserManager

logger = logging.getLogger(__name__)


async def build_props_handlers(
    *, transcript_id: UUID, verbose_prefix: str | None, compositor: Compositor, max_lines: int = DEFAULT_MAX_LINES
) -> list[BaseHandler]:
    """Build standard handlers for props agent workflows.

    # TODO: Refactor display config threading. Currently `verbose` and `max_lines` are passed
    # separately from CLI through run_critic/run_grader, while `verbose_prefix` is constructed
    # mid-way from internal context (transcript_id, snapshot_slug, etc.). Consider consolidating
    # into a single `DisplayConfig | None` param constructed at the same level as the prefix,
    # with CLI just passing `max_lines: int | None` (None = no display).

    Always includes DatabaseEventHandler for transcript persistence.
    Conditionally includes CompactDisplayHandler if verbose_prefix is provided.

    Args:
        transcript_id: Transcript ID for database event tracking
        verbose_prefix: Optional prefix for verbose display (e.g., "[CRITIC snapshot-slug] ").
                       If None, no verbose handler is added.
        compositor: Compositor instance for extracting server schemas
        max_lines: Max lines per event in verbose display (default from common_options)
    """
    handlers: list[BaseHandler] = [DatabaseEventHandler(transcript_id=transcript_id)]

    if verbose_prefix is not None:
        display_handler = await CompactDisplayHandler.from_compositor(
            compositor, max_lines=max_lines, prefix=verbose_prefix
        )
        handlers.append(display_handler)

    return handlers


class AgentEnvironment:
    """Base class for SQL-based agent environments with HTTP MCP server.

    Manages complete agent lifecycle:
    1. Creates temporary workspace directory
    2. Creates temporary database user with scoped access (via user_manager_factory)
    3. Starts HTTP MCP server with agent-specific tools (via mcp_server_factory)
    4. Creates Docker container with:
       - docker_exec tool available
       - Hydrated snapshots mounted at /snapshots/<slug>/
       - Database credentials in PG* env vars
       - MCP server URL/token in env vars
    5. Cleans up in reverse order on exit

    Subclasses configure the agent-specific parts by passing factories to __init__.

    Example subclass:
        class CriticAgentEnvironment(AgentEnvironment):
            def __init__(self, snapshot_slug, docker_client, hydrator, critic_run_id):
                super().__init__(
                    docker_client=docker_client,
                    user_manager_factory=lambda: CriticUserManager(...),
                    mcp_server_factory=lambda auth: create_critic_server(auth, ...),
                    hydrator=hydrator,
                    snapshot_slugs=[snapshot_slug],
                    workspace_prefix="critic_workspace_",
                )

    Usage:
        async with CriticAgentEnvironment(...) as compositor:
            # compositor has docker_exec tool
            # agent uses docker_exec to run commands and call MCP server
            ...
    """

    def __init__(
        self,
        docker_client: aiodocker.Docker,
        user_manager_factory: Callable[[], TempUserManager],
        mcp_server_factory: Callable[[AuthProvider], FastMCP],
        hydrator: SnapshotHydrator,
        *,
        snapshot_slugs: Sequence[SnapshotSlug] = (),
        workspace_prefix: str = "agent_workspace_",
        mount_properties: bool = False,
    ):
        """Create agent environment.

        Args:
            docker_client: Async Docker client (managed by caller)
            user_manager_factory: Factory that creates a TempUserManager.
                Called during __aenter__ to create scoped DB user for this run.
                Example: lambda: CriticUserManager(db_config.admin, run_id)
            mcp_server_factory: Factory that takes AuthProvider and returns FastMCP server.
                Called during __aenter__ with auth provider generated for HTTP authentication.
                Example: lambda auth: create_critic_server(run_id, snapshot_slug, auth=auth)
            hydrator: Snapshot hydrator for loading specimen code
            snapshot_slugs: Snapshots to hydrate and mount at /snapshots/<slug>/
            workspace_prefix: Prefix for temporary workspace directory (default: "agent_workspace_")
            mount_properties: Whether to mount property definitions at /props (default: False)
        """
        self._docker_client = docker_client
        self._user_manager_factory = user_manager_factory
        self._mcp_server_factory = mcp_server_factory
        self._hydrator = hydrator
        self._snapshot_slugs = snapshot_slugs
        self._workspace_prefix = workspace_prefix
        self._mount_properties = mount_properties

        # Managed resources (created in __aenter__, cleaned up in __aexit__)
        self._workspace_tmpdir: tempfile.TemporaryDirectory[str] | None = None
        self._user_manager: TempUserManager | None = None
        self._http_compositor: PropertiesDockerCompositorHTTP | None = None

    async def __aenter__(self) -> PropertiesDockerCompositor:
        """Start agent environment: workspace, user, HTTP server, container.

        Returns:
            PropertiesDockerCompositor with docker_exec tool available
        """
        # Create temporary workspace directory
        self._workspace_tmpdir = tempfile.TemporaryDirectory(prefix=self._workspace_prefix)
        workspace_path = Path(self._workspace_tmpdir.__enter__())

        # Create temporary database user with scoped access
        self._user_manager = self._user_manager_factory()
        temp_creds = await self._user_manager.__aenter__()

        logger.info(f"Created temporary database user: {temp_creds.username}")

        # Get container DB config with temp user credentials
        db_config = get_database_config()
        container_db = db_config.for_container_user(temp_creds)

        # Start HTTP MCP server + Docker container
        # (PropertiesDockerCompositorHTTP handles HTTP server lifecycle and container setup)
        self._http_compositor = PropertiesDockerCompositorHTTP(
            workspace_root=workspace_path,
            docker_client=self._docker_client,
            server_factory=self._mcp_server_factory,
            db_conn=container_db,
            hydrator=self._hydrator,
            snapshot_slugs=self._snapshot_slugs,
            mount_properties=self._mount_properties,
        )

        compositor = await self._http_compositor.__aenter__()

        logger.info(f"Started agent environment with {len(self._snapshot_slugs)} snapshot(s)")

        return compositor

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Clean up agent environment: compositor, user, workspace (reverse order)."""
        try:
            # Clean up HTTP compositor first (HTTP server + container)
            if self._http_compositor is not None:
                await self._http_compositor.__aexit__(exc_type, exc_val, exc_tb)
                self._http_compositor = None
        finally:
            # Clean up temporary database user
            if self._user_manager is not None:
                await self._user_manager.__aexit__(exc_type, exc_val, exc_tb)
                self._user_manager = None

            # Clean up temp workspace directory
            if self._workspace_tmpdir is not None:
                self._workspace_tmpdir.__exit__(None, None, None)
                self._workspace_tmpdir = None
