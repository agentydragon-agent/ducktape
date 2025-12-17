"""HTTP mode compositor - manages MCP-over-HTTP server lifecycle with container."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from dataclasses import dataclass
import logging
from pathlib import Path
import secrets
from typing import TYPE_CHECKING, cast

from fastmcp import FastMCP
from fastmcp.server.auth import AuthProvider, StaticTokenVerifier
import uvicorn

from adgn.mcp._shared.container_session import BindMount
from adgn.props.docker_env import PROPS_NETWORK_NAME, PropertiesDockerCompositor, get_docker_network_gateway_async
from adgn.props.hydration import SnapshotHydrator
from adgn.props.ids import SnapshotSlug
from adgn.util.net import pick_free_port, wait_for_port

if TYPE_CHECKING:
    import aiodocker

    from adgn.props.db.config import DbConnectionConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ServerHandle:
    """Handle to a running ephemeral MCP HTTP server."""

    port: int
    token: str
    url: str  # Full URL for convenience


@asynccontextmanager
async def launch_mcp_http_server(
    server_factory: Callable[[AuthProvider], FastMCP],
    *,
    host: str = "0.0.0.0",
    container_host: str,
    startup_timeout: float = 10.0,
):
    """Launch an ephemeral MCP HTTP server, yield handle, shut down on exit.

    Port and token are generated internally (ephemeral, no persistence needed).

    Args:
        server_factory: Factory function that creates a FastMCP server.
            Called with (auth: AuthProvider) - server should NOT configure auth itself.
        host: Host to bind to (default 0.0.0.0 for Docker accessibility).
        container_host: Hostname that containers use to reach the host (required).
            For host.docker.internal-based setups, use "host.docker.internal".
            For internal Docker networks, pass the gateway IP (e.g., "172.19.0.1").
        startup_timeout: Seconds to wait for server to become ready.

    Yields:
        ServerHandle with port, token, and full URL.

    Example:
        async with launch_mcp_http_server(create_grader_server) as handle:
            # Server running at handle.url with handle.token
            # Pass as extra_env to PropertiesDockerCompositor:
            async with PropertiesDockerCompositor(
                workspace_root, docker_client,
                hydrator=hydrator,
                extra_env={
                    "MCP_SERVER_URL": handle.url,
                    "MCP_SERVER_TOKEN": handle.token,
                },
            ) as comp:
                ...
    """
    token = secrets.token_hex(32)
    # StaticTokenVerifier requires token metadata with at least client_id
    auth = StaticTokenVerifier({token: {"client_id": "mcp_agent", "scopes": []}})
    port = pick_free_port(host="127.0.0.1")
    server = server_factory(auth)
    app = server.http_app(transport="streamable-http")
    config = uvicorn.Config(app=app, host=host, port=port, log_level="warning", access_log=False)
    uv_server = uvicorn.Server(config)
    server_task = asyncio.create_task(uv_server.serve())

    try:
        await asyncio.to_thread(wait_for_port, "127.0.0.1", port, timeout_secs=startup_timeout)
        url = f"http://{container_host}:{port}/mcp"
        logger.info(f"MCP HTTP server started at {url}")
        yield ServerHandle(port=port, token=token, url=url)

    finally:
        # Signal shutdown
        uv_server.should_exit = True

        # Wait for graceful shutdown with timeout
        try:
            await asyncio.wait_for(server_task, timeout=5.0)
        except TimeoutError:
            logger.warning("Server shutdown timed out, cancelling")
            server_task.cancel()
            with suppress(asyncio.CancelledError):
                await server_task
        except asyncio.CancelledError:
            # Suppress cancellation during shutdown; this is expected if the task is cancelled.
            pass

        logger.info(f"MCP HTTP server on port {port} shut down")


class PropertiesDockerCompositorHTTP(PropertiesDockerCompositor):
    """Compositor subclass that manages HTTP-mode MCP server and container lifecycle.

    This subclass extends PropertiesDockerCompositor to coordinate:
    1. MCP-over-HTTP server (runs on host, exposed via loopback)
    2. Docker container with properties environment (connects to server via host network)

    The container receives MCP_SERVER_URL and MCP_SERVER_TOKEN via environment,
    allowing in-container code to connect to the MCP server over HTTP.

    HTTP mode has fixed configuration:
    - network_mode: PROPS_NETWORK_NAME (container must reach host)
    - workspace_mode: "rw" (always read-write for agent work)
    - ephemeral: False (always persistent container)
    - db_conn: Required (agent needs database access)
    - hydrator: Required (no default)
    - container_host: Auto-computed from network gateway IP

    Example:
        hydrator = SnapshotHydrator.from_env()
        async with PropertiesDockerCompositorHTTP(
            workspace_root=Path("/workspace"),
            docker_client=docker_client,
            server_factory=lambda token: create_grader_server(token),
            db_conn=db_config,
            hydrator=hydrator,
            snapshot_slugs=["ducktape/2025-11-26-00"],
        ) as comp:
            # comp is a PropertiesDockerCompositor with HTTP server running
            # Container has MCP_SERVER_URL and MCP_SERVER_TOKEN in environment
            ...

    TODO: Move HTTP-mode instructions (system prompt additions, etc.) into this class
          to fully encapsulate the HTTP mode configuration.
    """

    def __init__(
        self,
        workspace_root: Path,
        docker_client: aiodocker.Docker,
        server_factory: Callable[[AuthProvider], FastMCP],
        db_conn: DbConnectionConfig,
        hydrator: SnapshotHydrator,
        *,
        snapshot_slugs: Sequence[SnapshotSlug] = (),
        mount_properties: bool = False,
        extra_binds: Sequence[BindMount] = (),
    ) -> None:
        """Create HTTP mode compositor.

        Args:
            workspace_root: Path to workspace directory to mount in container
            docker_client: Async Docker client (managed by caller)
            server_factory: Factory function that takes an AuthProvider and returns FastMCP server
            db_conn: Database connection config (required for HTTP mode)
            hydrator: Snapshot hydrator (required - no default)
            snapshot_slugs: Snapshots to hydrate and mount (default: none)
            mount_properties: Whether to mount property definitions at /props (default: False)
            extra_binds: Additional bind mounts (default empty tuple)
        """
        # Store server factory for __aenter__ (gateway IP will be computed there)
        self._server_factory = server_factory
        self._exit_stack: AsyncExitStack | None = None

        # Initialize parent with HTTP mode configuration
        # HTTP mode is always: persistent (not ephemeral), RW workspace
        super().__init__(
            workspace_root,
            docker_client,
            mount_properties=mount_properties,
            hydrator=hydrator,
            snapshot_slugs=snapshot_slugs,
            db_conn=db_conn,
            extra_binds=extra_binds,
            workspace_mode="rw",  # HTTP mode always RW
            network_mode=PROPS_NETWORK_NAME,  # Must allow container→host communication
            extra_env=None,  # Will be set in __aenter__ after server starts
            ephemeral=False,  # HTTP mode always persistent
        )

    async def __aenter__(self) -> PropertiesDockerCompositor:
        """Start HTTP server, then start compositor with server URL/token in environment."""
        self._exit_stack = AsyncExitStack()
        await self._exit_stack.__aenter__()

        # Compute gateway IP for the props network (async)
        container_host = await get_docker_network_gateway_async(self._docker_client, PROPS_NETWORK_NAME)

        # Start HTTP server first
        server_handle = await self._exit_stack.enter_async_context(
            launch_mcp_http_server(self._server_factory, container_host=container_host)
        )

        # Inject MCP server URL and token into container environment
        self._extra_env = {"MCP_SERVER_URL": server_handle.url, "MCP_SERVER_TOKEN": server_handle.token}

        # Now start the parent compositor (which will use the extra_env)
        return cast(PropertiesDockerCompositor, await super().__aenter__())

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Clean up compositor and HTTP server (reverse order)."""
        if self._exit_stack:
            await self._exit_stack.__aexit__(exc_type, exc_val, exc_tb)
            self._exit_stack = None
        await super().__aexit__(exc_type, exc_val, exc_tb)
