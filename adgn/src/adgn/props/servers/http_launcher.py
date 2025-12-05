"""Ephemeral MCP HTTP server launcher.

Context manager for running MCP servers over HTTP during agent execution.
Servers are launched on demand with dynamic port allocation and shut down
when the context exits.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
import logging
import secrets
from typing import TYPE_CHECKING

import uvicorn

from adgn.util.net import pick_free_port, wait_for_port

if TYPE_CHECKING:
    from fastmcp import FastMCP

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
    host: str = "0.0.0.0",  # noqa: S104 - binding to all interfaces for Docker access
    port: int | None = None,
    token: str | None = None,
    startup_timeout: float = 10.0,
):
    """Launch an ephemeral MCP HTTP server, yield handle, shut down on exit.

    Args:
        server_factory: Factory function that creates a FastMCP server.
            Called with (token: str) to allow server to configure auth.
        host: Host to bind to. Default 0.0.0.0 for Docker accessibility.
        port: Port to bind to. If None, a free port is picked automatically.
        token: Bearer token for authentication. If None, generated randomly.
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
    # Generate token if not provided (ephemeral, no persistence needed)
    token = token or secrets.token_hex(32)
    port = port or pick_free_port(host="127.0.0.1")

    # Create server with auth configured
    server = server_factory(token)

    # Get Starlette app from FastMCP
    # Use streamable-http transport for MCP SDK compatibility
    app = server.http_app(transport="streamable-http")

    # Configure uvicorn
    config = uvicorn.Config(
        app=app,
        host=host,
        port=port,
        log_level="warning",
        access_log=False,
    )
    uv_server = uvicorn.Server(config)

    # Start server in background task
    server_task = asyncio.create_task(uv_server.serve())

    try:
        # Wait for server to be ready
        await asyncio.to_thread(
            wait_for_port,
            "127.0.0.1",
            port,
            timeout_secs=startup_timeout,
        )

        url = f"http://host.docker.internal:{port}"
        handle = ServerHandle(port=port, token=token, url=url)
        logger.info(f"MCP HTTP server started on port {port}")

        yield handle

    finally:
        # Signal shutdown
        uv_server.should_exit = True

        # Wait for graceful shutdown with timeout
        try:
            await asyncio.wait_for(server_task, timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("Server shutdown timed out, cancelling")
            server_task.cancel()
            with asyncio.suppress(asyncio.CancelledError):
                await server_task
        except asyncio.CancelledError:
            pass

        logger.info(f"MCP HTTP server on port {port} shut down")
