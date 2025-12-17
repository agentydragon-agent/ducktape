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
import os
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

    from adgn.agent.bootstrap import TypedBootstrapBuilder
    from adgn.mcp._shared.mounted import Mounted
    from adgn.mcp.compositor.server import Compositor
    from adgn.mcp.exec.docker.server import ContainerExecServer
    from adgn.openai_utils.model import FunctionCallItem
    from adgn.props.db.temp_user_manager import TempUserManager

logger = logging.getLogger(__name__)

# Toggle for MCP HTTP transport (shared across all agents)
# Set via environment variable: ADGN_USE_MCP_HTTP=1
# Default: False (use in-proc MCP unless explicitly enabled)
USE_MCP_HTTP = os.getenv("ADGN_USE_MCP_HTTP", "").lower() in ("1", "true", "yes")


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

    Subclasses configure the agent-specific parts by passing factories to __init__
    and optionally overriding bootstrap_mcp_resources() and bootstrap_items().

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

            def bootstrap_mcp_resources(self) -> Sequence[tuple[str, str]]:
                return [
                    ("Snapshot Slug", CRITIC_SNAPSHOT_SLUG_RESOURCE_URI),
                    ("Scope", CRITIC_SCOPE_RESOURCE_URI),
                ]

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
        workspace_root: Path | None = None,
        mount_properties: bool = False,
        http_mode: bool = USE_MCP_HTTP,
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
            workspace_prefix: Prefix for temporary workspace directory (only used if workspace_root is None)
            workspace_root: Pre-existing workspace directory to use (if None, creates temporary directory)
            mount_properties: Whether to mount property definitions at /props (default: False)
            http_mode: Whether to use HTTP mode for MCP server (default: USE_MCP_HTTP env var)
        """
        self._docker_client = docker_client
        self._user_manager_factory = user_manager_factory
        self._mcp_server_factory = mcp_server_factory
        self._hydrator = hydrator
        self._snapshot_slugs = snapshot_slugs
        self._workspace_prefix = workspace_prefix
        self._workspace_root = workspace_root
        self._mount_properties = mount_properties
        self._http_mode = http_mode

        # Managed resources (created in __aenter__, cleaned up in __aexit__)
        self._workspace_tmpdir: tempfile.TemporaryDirectory[str] | None = None
        self._user_manager: TempUserManager | None = None
        self._http_compositor: PropertiesDockerCompositorHTTP | None = None
        self._compositor: Compositor | None = None

    def bootstrap_mcp_resources(self) -> Sequence[tuple[str, str]]:
        """Return list of (label, URI) tuples for MCP resources to read during bootstrap.

        Subclasses override this to specify which resources should be read from the
        MCP server during bootstrap (HTTP mode only).

        Returns:
            List of (label, URI) pairs - e.g., [("Snapshot Slug", "resource://critic/snapshot-slug")]
        """
        return []

    def bootstrap_items(self, builder: TypedBootstrapBuilder, runtime: Mounted[ContainerExecServer]) -> list:
        """Build bootstrap items (function calls) for agent initialization.

        Default implementation uses make_mcp_http_bootstrap_calls with bootstrap_mcp_resources().
        Subclasses can override to customize bootstrap behavior.

        Args:
            builder: Bootstrap builder for generating typed tool calls
            runtime: Mounted runtime server (comp.runtime)

        Returns:
            List of FunctionCallItems to inject before agent sampling
        """
        resources = self.bootstrap_mcp_resources()
        if resources:
            return make_mcp_http_bootstrap_calls(builder, runtime, resources)
        return []

    async def __aenter__(self) -> PropertiesDockerCompositor:
        """Start agent environment: workspace, user, HTTP server, container.

        Returns:
            PropertiesDockerCompositor with docker_exec tool available
        """
        # Use provided workspace_root or create temporary workspace directory
        if self._workspace_root is not None:
            workspace_path = self._workspace_root
            logger.info(f"Using existing workspace: {workspace_path}")
        else:
            self._workspace_tmpdir = tempfile.TemporaryDirectory(prefix=self._workspace_prefix)
            workspace_path = Path(self._workspace_tmpdir.__enter__())
            logger.info(f"Created temporary workspace: {workspace_path}")

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
        self._compositor = compositor

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


# =============================================================================
# MCP-over-HTTP Bootstrap Helpers
# =============================================================================


def make_mcp_http_bootstrap_script(resources: Sequence[tuple[str, str]]) -> str:
    """Generate Python bootstrap script for MCP-over-HTTP.

    Args:
        resources: List of (label, uri) tuples to read during bootstrap

    Returns:
        Python script as string that connects to MCP server, lists tools, and reads resources

    Example:
        script = make_mcp_http_bootstrap_script([
            ("Snapshot Slug", "resource://critic/snapshot-slug"),
            ("Scope", "resource://critic/scope"),
        ])
    """
    # Build resources list literal for the script
    resources_repr = "[\n"
    for label, uri in resources:
        resources_repr += f'            ("{label}", "{uri}"),\n'
    resources_repr += "        ]"

    return f"""
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
        resources = {resources_repr}
        for label, uri in resources:
            print(f"=== {{label}} ===")
            result = await session.read_resource(uri)
            print(json.dumps(result.model_dump(mode="json"), indent=2))

asyncio.run(bootstrap())
"""


def make_mcp_http_bootstrap_calls(
    builder: TypedBootstrapBuilder,
    runtime: Mounted[ContainerExecServer],
    resources: Sequence[tuple[str, str]],
    *,
    timeout_ms: int = 15_000,
) -> list[FunctionCallItem]:
    """Build bootstrap calls for MCP-over-HTTP mode.

    Shows connection instructions and runs a bootstrap script that:
    - Connects to MCP server via HTTP
    - Lists available tools
    - Reads specified resources

    Args:
        builder: Bootstrap builder for generating typed tool calls
        runtime: Mounted runtime server (e.g., comp.runtime)
        resources: List of (label, uri) tuples to read during bootstrap
        timeout_ms: Script execution timeout (default: 15 seconds)

    Returns:
        List of bootstrap calls (read connection docs + exec script)

    Example:
        from adgn.agent.bootstrap import TypedBootstrapBuilder, read_package_file_call

        builder = TypedBootstrapBuilder.for_server(runtime.server)
        bootstrap_calls = make_mcp_http_bootstrap_calls(
            builder, comp.runtime,
            resources=[
                ("Snapshot Slug", CRITIC_SNAPSHOT_SLUG_RESOURCE_URI),
                ("Scope", CRITIC_SCOPE_RESOURCE_URI),
            ]
        )
    """
    from adgn.agent.bootstrap import docker_exec_call_mounted, read_package_file_call

    bootstrap_script = make_mcp_http_bootstrap_script(resources)

    return [
        # Show MCP-over-HTTP connection instructions first
        read_package_file_call(builder, runtime, "adgn.props.prompts", "mcp_http_connection.md"),
        # Then run the bootstrap script that demonstrates the connection
        docker_exec_call_mounted(builder, runtime, cmd=["python3", "-c", bootstrap_script], timeout_ms=timeout_ms),
    ]
