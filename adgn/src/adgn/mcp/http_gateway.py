from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
import contextlib
from contextlib import asynccontextmanager
from dataclasses import dataclass
import secrets

import aiodocker
from fastmcp import FastMCP
from fastmcp.server.auth import AuthProvider, StaticTokenVerifier
import uvicorn

from net_util import get_docker_network_gateway_async, pick_free_port, wait_for_port


@dataclass
class MCPHttpGateway:
    url_for_container: str
    token: str
    port: int
    server: FastMCP
    _shutdown: Callable[[], Awaitable[None]]

    async def shutdown(self) -> None:
        await self._shutdown()


async def start_mcp_http_gateway(
    *,
    make_server: Callable[[AuthProvider], FastMCP],
    docker_client: aiodocker.Docker,
    network_name: str,
    host: str = "0.0.0.0",
    log_level: str = "warning",
) -> MCPHttpGateway:
    """Start a FastMCP HTTP server and return container-reachable URL/token.

    This mirrors the props agent setup pattern without any DB/snapshot wiring.
    """

    token = secrets.token_hex(32)
    auth = StaticTokenVerifier({token: {"client_id": "mcp_client", "scopes": []}})
    # TODO: Consider binding to docker gateway only instead of 0.0.0.0
    port = pick_free_port(host=host)

    server = make_server(auth)
    app = server.http_app(transport="streamable-http")
    config = uvicorn.Config(app=app, host=host, port=port, log_level=log_level, access_log=False)
    uv_server = uvicorn.Server(config)
    server_task = asyncio.create_task(uv_server.serve())

    async def _shutdown() -> None:
        uv_server.should_exit = True
        try:
            await asyncio.wait_for(server_task, timeout=5.0)
        except TimeoutError:
            server_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await server_task

    # Wait for server to be ready
    await asyncio.to_thread(wait_for_port, "127.0.0.1", port, timeout_secs=10.0)

    gateway = await get_docker_network_gateway_async(docker_client, network_name)
    url_for_container = f"http://{gateway}:{port}/mcp"

    return MCPHttpGateway(
        url_for_container=url_for_container, token=token, port=port, server=server, _shutdown=_shutdown
    )


@asynccontextmanager
async def mcp_http_gateway(
    *,
    make_server: Callable[[AuthProvider], FastMCP],
    docker_client: aiodocker.Docker,
    network_name: str,
    host: str = "0.0.0.0",
    log_level: str = "warning",
) -> AsyncIterator[MCPHttpGateway]:
    gateway = await start_mcp_http_gateway(
        make_server=make_server, docker_client=docker_client, network_name=network_name, host=host, log_level=log_level
    )
    try:
        yield gateway
    finally:
        await gateway.shutdown()
