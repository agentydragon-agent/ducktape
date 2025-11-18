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


class InfrastructureRegistry:
    """Shared registry for managing per-agent infrastructure."""

    def __init__(
        self,
        persistence: SQLitePersistence,
        docker_client: DockerClient,
        mcp_config: MCPConfig,
        initial_policy: str | None,
    ):
        self.persistence = persistence
        self.docker_client = docker_client
        self.mcp_config = mcp_config
        self.initial_policy = initial_policy
        # Infrastructure cache: agent_id → (RunningInfrastructure, FastAPI app)
        self._infra_cache: dict[str, tuple[RunningInfrastructure, FastAPI]] = {}
        self._infra_locks: dict[str, asyncio.Lock] = {}

    async def get_or_create_infrastructure(self, agent_id: str) -> tuple[RunningInfrastructure, FastAPI]:
        """Get or create infrastructure for an agent_id."""
        # Ensure we have a lock for this agent_id
        if agent_id not in self._infra_locks:
            self._infra_locks[agent_id] = asyncio.Lock()

        async with self._infra_locks[agent_id]:
            if agent_id in self._infra_cache:
                return self._infra_cache[agent_id]

            logger.info(f"Creating infrastructure for agent_id={agent_id}")
            running = await create_bridge_infrastructure(
                agent_id=agent_id,
                persistence=self.persistence,
                docker_client=self.docker_client,
                mcp_config=self.mcp_config,
                initial_policy=self.initial_policy,
            )

            # Start the infrastructure
            await running.__aenter__()

            # Get the compositor's HTTP app
            compositor_app: FastAPI = running.compositor.http_app()  # type: ignore[assignment]

            self._infra_cache[agent_id] = (running, compositor_app)
            logger.info(f"Infrastructure ready for agent_id={agent_id}")
            return (running, compositor_app)

    async def get_compositor_app(self, agent_id: str) -> FastAPI:
        """Get compositor app for an agent_id."""
        _, app = await self.get_or_create_infrastructure(agent_id)
        return app

    def get_running_infrastructure(self, agent_id: str) -> RunningInfrastructure | None:
        """Get running infrastructure if it exists (doesn't create)."""
        if agent_id in self._infra_cache:
            return self._infra_cache[agent_id][0]
        return None


async def create_mcp_server_app(
    auth_tokens_path: Path,
    registry: InfrastructureRegistry,
) -> FastAPI:
    """Create token-authenticated MCP server app.

    Routes MCP-over-HTTP requests to per-agent compositor apps based on token.
    """

    class CompositorRoutingMiddleware(BaseHTTPMiddleware):
        """Routes requests to the appropriate agent's compositor app."""

        async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
            # Get agent_id set by TokenAuthMiddleware
            agent_id = request.state.agent_id

            # Get the compositor app for this agent
            compositor_app = await registry.get_compositor_app(agent_id)

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

    # Create FastAPI app for MCP server
    token_mapping = TokenMapping(auth_tokens_path)
    mcp_app = FastAPI(title="MCP Server")

    # Order matters: routing first, then token auth (outermost middleware runs first)
    mcp_app.add_middleware(CompositorRoutingMiddleware)
    mcp_app.add_middleware(TokenAuthMiddleware, token_mapping=token_mapping)

    return mcp_app


async def create_management_ui_app(
    registry: InfrastructureRegistry,
) -> FastAPI:
    """Create management UI app with WebSocket channels.

    Provides web interface for managing approvals, policy, and agent state.
    No token authentication - intended for localhost access or separate auth.
    """
    from fastapi import WebSocket

    ui_app = FastAPI(title="Management UI")

    @ui_app.websocket("/ws/policy")
    async def ws_policy(websocket: WebSocket, agent_id: str):
        """Policy channel - view/edit approval policy."""
        await websocket.accept()
        # TODO: Implement policy channel
        await websocket.send_json({"type": "not_implemented", "message": "Policy channel coming soon"})
        await websocket.close()

    @ui_app.websocket("/ws/approvals")
    async def ws_approvals(websocket: WebSocket, agent_id: str):
        """Approvals channel - pending approvals and decisions."""
        await websocket.accept()
        # TODO: Implement approvals channel
        await websocket.send_json({"type": "not_implemented", "message": "Approvals channel coming soon"})
        await websocket.close()

    @ui_app.websocket("/ws/mcp")
    async def ws_mcp(websocket: WebSocket, agent_id: str):
        """MCP channel - server state and tool calls."""
        await websocket.accept()
        # TODO: Implement MCP channel
        await websocket.send_json({"type": "not_implemented", "message": "MCP channel coming soon"})
        await websocket.close()

    @ui_app.get("/api/agents")
    async def list_agents():
        """List all active agents."""
        # TODO: Return list of agents from registry
        return {"agents": []}

    @ui_app.get("/health")
    async def health():
        """Health check endpoint."""
        return {"status": "ok"}

    return ui_app


async def create_multi_tenant_app(
    auth_tokens_path: Path,
    persistence: SQLitePersistence,
    docker_client: DockerClient,
    mcp_config: MCPConfig,
    initial_policy: str | None,
) -> FastAPI:
    """Backward-compatible wrapper - creates only MCP server.

    DEPRECATED: Use create_mcp_server_app() and create_management_ui_app() separately.
    """
    registry = InfrastructureRegistry(
        persistence=persistence,
        docker_client=docker_client,
        mcp_config=mcp_config,
        initial_policy=initial_policy,
    )
    return await create_mcp_server_app(auth_tokens_path=auth_tokens_path, registry=registry)
