"""HTTP MCP Bridge Server - exposes Compositor over HTTP/SSE transport.

This is a standard MCP server (Compositor) exposed via HTTP transport.
External agents connect using MCP-over-HTTP and get policy-gated access to tools.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging
from pathlib import Path

from docker import DockerClient
from fastapi import FastAPI, Request, Response
from fastmcp.mcp_config import MCPConfig
from starlette.middleware.base import BaseHTTPMiddleware

from adgn.agent.mcp_bridge.auth import TokenAuthMiddleware, TokenMapping
from adgn.agent.persist.sqlite import SQLitePersistence
from adgn.agent.runtime.infrastructure import MCPInfrastructure, RunningInfrastructure
from adgn.agent.runtime.sidecars import SidecarBundle

logger = logging.getLogger(__name__)


async def create_bridge_infrastructure(
    agent_id: str,
    persistence: SQLitePersistence,
    docker_client: DockerClient,
    mcp_config: MCPConfig,
    initial_policy: str | None = None,
):
    """Create RunningInfrastructure for external agent HTTP bridge."""
    # Create infrastructure builder
    builder = MCPInfrastructure(
        agent_id=agent_id, persistence=persistence, docker_client=docker_client, initial_policy=initial_policy
    )

    # Start core infrastructure
    running = await builder.start(mcp_config)

    # Attach sidecars (none for external agents)
    bundle = SidecarBundle.for_external_agent()
    await bundle.attach_all(running)

    return running


async def create_multi_tenant_app(
    auth_tokens_path: Path,
    persistence: SQLitePersistence,
    docker_client: DockerClient,
    mcp_config: MCPConfig,
    initial_policy: str | None,
) -> FastAPI:
    """Create multi-tenant FastAPI app with token authentication.

    Each token maps to an agent_id. Infrastructure is created lazily per agent_id
    and cached for subsequent requests.
    """
    # Infrastructure cache: agent_id → (RunningInfrastructure, FastAPI app)
    infra_cache: dict[str, tuple[RunningInfrastructure, FastAPI]] = {}
    infra_locks: dict[str, asyncio.Lock] = {}

    async def get_compositor_app(agent_id: str) -> FastAPI:
        """Get or create compositor app for an agent_id."""
        # Ensure we have a lock for this agent_id
        if agent_id not in infra_locks:
            infra_locks[agent_id] = asyncio.Lock()

        async with infra_locks[agent_id]:
            if agent_id in infra_cache:
                return infra_cache[agent_id][1]

            logger.info(f"Creating infrastructure for agent_id={agent_id}")
            running = await create_bridge_infrastructure(
                agent_id=agent_id,
                persistence=persistence,
                docker_client=docker_client,
                mcp_config=mcp_config,
                initial_policy=initial_policy,
            )

            # Start the infrastructure
            await running.__aenter__()

            # Get the compositor's HTTP app
            compositor_app = running.compositor.http_app()

            infra_cache[agent_id] = (running, compositor_app)
            logger.info(f"Infrastructure ready for agent_id={agent_id}")
            return compositor_app

    class CompositorRoutingMiddleware(BaseHTTPMiddleware):
        """Routes requests to the appropriate agent's compositor app."""

        async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
            # Get agent_id set by TokenAuthMiddleware
            agent_id = request.state.agent_id

            # Get the compositor app for this agent
            compositor_app = await get_compositor_app(agent_id)

            # Forward request to the compositor's ASGI app
            # We need to call the ASGI app directly with the scope
            scope = request.scope

            # Create response containers
            response_started = False
            status_code = 200
            headers = []
            body_parts = []

            async def receive():
                return await request.receive()

            async def send(message):
                nonlocal response_started, status_code, headers
                if message["type"] == "http.response.start":
                    response_started = True
                    status_code = message["status"]
                    headers = message.get("headers", [])
                elif message["type"] == "http.response.body":
                    body_parts.append(message.get("body", b""))

            # Call the compositor app
            await compositor_app(scope, receive, send)

            # Return the response
            response_headers = {k.decode(): v.decode() for k, v in headers}
            body = b"".join(body_parts)
            return Response(content=body, status_code=status_code, headers=response_headers)

    # Create root FastAPI app with middleware
    token_mapping = TokenMapping(auth_tokens_path)
    root_app = FastAPI()

    # Order matters: token auth first, then routing
    root_app.add_middleware(CompositorRoutingMiddleware)
    root_app.add_middleware(TokenAuthMiddleware, token_mapping=token_mapping)

    return root_app
