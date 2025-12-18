"""HTTP mode compositor - manages MCP-over-HTTP server lifecycle with container."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from dataclasses import dataclass
import logging
from pathlib import Path
import secrets
from typing import TYPE_CHECKING

from fastmcp import FastMCP
from fastmcp.server.auth import AuthProvider, StaticTokenVerifier
import uvicorn

from adgn.mcp._shared.container_session import BindMount
from adgn.mcp.compositor.server import Compositor
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
        agent_environment,  # AgentEnvironment with _make_mcp_server method
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
            agent_environment: AgentEnvironment instance (provides _make_mcp_server method)
            db_conn: Database connection config (required for HTTP mode)
            hydrator: Snapshot hydrator (required - no default)
            snapshot_slugs: Snapshots to hydrate and mount (default: none)
            mount_properties: Whether to mount property definitions at /props (default: False)
            extra_binds: Additional bind mounts (default empty tuple)
        """
        # Store agent environment for __aenter__ (will call _make_mcp_server method)
        self._agent_environment = agent_environment
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
        """Start HTTP server, then start compositor with server URL/token in environment.

        Manually orchestrates the following order:
        1. Mount resources/compositor_meta (grandparent)
        2. Hydrate snapshots (populate _hydrated_paths)
        3. Start MCP HTTP server (needs hydrated paths)
        4. Set container environment with MCP server URL/token
        5. Create Docker exec server (uses environment)
        """
        self._exit_stack = AsyncExitStack()
        await self._exit_stack.__aenter__()

        # Compute gateway IP for the props network (async)
        container_host = await get_docker_network_gateway_async(self._docker_client, PROPS_NETWORK_NAME)

        # Step 1: Mount resources and compositor_meta (call grandparent)
        await Compositor.__aenter__(self)

        # Step 2: Hydrate snapshots (copied from PropertiesDockerCompositor)
        if self._hydrator and self._snapshot_slugs:
            self._snapshot_stack = AsyncExitStack()
            await self._snapshot_stack.__aenter__()

            extra_snapshot_binds: list[BindMount] = []
            for slug in self._snapshot_slugs:
                hydrated = await self._snapshot_stack.enter_async_context(self._hydrator.hydrate(slug))
                bind = BindMount(
                    host_path=hydrated.content_root.resolve(),
                    container_path=self.snapshot_container_path(slug),
                    mode="ro",
                )
                extra_snapshot_binds.append(bind)
                self._hydrated_paths[slug] = bind.host_path
                logger.debug(f"Hydrated {slug} → {hydrated.content_root} (mount as {bind.container_path})")

            self._extra_binds = [*self._extra_binds, *extra_snapshot_binds]
            logger.info(f"Mounted {len(extra_snapshot_binds)} snapshots (read-only)")

        # Step 3: Copy hydrated paths to agent environment and start MCP server
        self._agent_environment._hydrated_paths = self._hydrated_paths
        server_handle = await self._exit_stack.enter_async_context(
            launch_mcp_http_server(
                lambda auth: self._agent_environment._make_mcp_server(auth), container_host=container_host
            )
        )

        # Step 4: Set container environment with MCP server credentials
        self._extra_env = {"MCP_SERVER_URL": server_handle.url, "MCP_SERVER_TOKEN": server_handle.token}

        # Step 5: Create Docker exec server (copied from PropertiesDockerCompositor)
        image_id = await ensure_critic_image_async(self._docker_client)
        docker_server = self._create_docker_server(image_id)
        self.runtime = await self.mount_inproc(DOCKER_MOUNT_PREFIX, docker_server, pinned=True)

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Clean up compositor and HTTP server (reverse order)."""
        logger.info("HTTP_COMP_DEBUG: starting __aexit__")
        # Clean up exit stack (HTTP server)
        if self._exit_stack:
            logger.info("HTTP_COMP_DEBUG: cleaning up exit stack (HTTP server)")
            await self._exit_stack.__aexit__(exc_type, exc_val, exc_tb)
            self._exit_stack = None
            logger.info("HTTP_COMP_DEBUG: exit stack cleaned up")

        # Clean up hydrated snapshots (if we did hydration)
        if self._snapshot_stack is not None:
            logger.info("HTTP_COMP_DEBUG: cleaning up snapshot stack")
            await self._snapshot_stack.__aexit__(exc_type, exc_val, exc_tb)
            self._snapshot_stack = None
            logger.info("HTTP_COMP_DEBUG: snapshot stack cleaned up")

        # Clean up grandparent (Compositor)
        logger.info("HTTP_COMP_DEBUG: calling Compositor.__aexit__")
        await Compositor.__aexit__(self, exc_type, exc_val, exc_tb)
        logger.info("HTTP_COMP_DEBUG: Compositor.__aexit__ complete")
