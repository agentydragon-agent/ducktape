"""Ephemeral MCP HTTP server launcher.

Context manager for running MCP servers over HTTP during agent execution.
Servers are launched on demand with dynamic port allocation and shut down
when the context exits.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
import logging
import secrets

from fastmcp import FastMCP
import uvicorn

from adgn.util.net import pick_free_port, wait_for_port

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ServerHandle:
    """Handle to a running ephemeral MCP HTTP server."""

    port: int
    token: str
    url: str  # Full URL for convenience


@asynccontextmanager
async def launch_mcp_http_server(
    server_factory: Callable[[str], FastMCP],
    *,
    host: str = "0.0.0.0",  # binding to all interfaces for Docker access
    container_host: str,  # hostname containers use to reach host (no default - caller must specify)
    startup_timeout: float = 10.0,
):
    """Launch an ephemeral MCP HTTP server, yield handle, shut down on exit.

    Port and token are generated internally (ephemeral, no persistence needed).

    Args:
        server_factory: Factory function that creates a FastMCP server.
            Called with (token: str) to allow server to configure auth.
        host: Host to bind to. Default 0.0.0.0 for Docker accessibility.
        container_host: Hostname that containers use to reach the host.
            Default "host.docker.internal" for non-internal networks.
            For internal Docker networks, pass the gateway IP (e.g., "172.19.0.1").
        startup_timeout: Seconds to wait for server to become ready.

    Yields:
        ServerHandle with port, token, and full URL.

    Example:
        async with launch_mcp_http_server(create_grader_server) as handle:
            # Server running at handle.url with handle.token
            wiring = properties_docker_spec(
                ...,
                extra_env={
                    "MCP_SERVER_URL": handle.url,
                    "MCP_SERVER_TOKEN": handle.token,
                },
            )
            ...
    """
    token = secrets.token_hex(32)
    port = pick_free_port(host="127.0.0.1")

    # Create server with auth configured
    server = server_factory(token)

    # Get Starlette app from FastMCP
    # Use streamable-http transport for MCP SDK compatibility
    app = server.http_app(transport="streamable-http")

    # Configure uvicorn
    config = uvicorn.Config(app=app, host=host, port=port, log_level="warning", access_log=False)
    uv_server = uvicorn.Server(config)

    # Start server in background task
    server_task = asyncio.create_task(uv_server.serve())

    try:
        # Wait for server to be ready
        await asyncio.to_thread(wait_for_port, "127.0.0.1", port, timeout_secs=startup_timeout)

        # FastMCP serves at /mcp for streamable-http transport
        url = f"http://{container_host}:{port}/mcp"
        handle = ServerHandle(port=port, token=token, url=url)
        logger.info(f"MCP HTTP server started at {url}")

        yield handle

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
