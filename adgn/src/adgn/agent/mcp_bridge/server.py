"""HTTP MCP Bridge Server - exposes Compositor over HTTP/SSE transport.

This is a standard MCP server (Compositor) exposed via HTTP transport.
External agents connect using MCP-over-HTTP and get policy-gated access to tools.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from docker import DockerClient
from fastapi import FastAPI, Request, Response, WebSocket
from fastmcp.client import Client
from fastmcp.mcp_config import MCPConfig
from starlette.middleware.base import BaseHTTPMiddleware

from adgn.agent.mcp_bridge.auth import TokenAuthMiddleware, TokenMapping, UITokenAuthMiddleware, generate_ui_token
from adgn.agent.mcp_bridge.servers.agents import AgentList, make_agents_server
from adgn.agent.mcp_bridge.types import AgentID, AgentMode
from adgn.agent.persist.sqlite import SQLitePersistence
from adgn.agent.runtime.infrastructure import MCPInfrastructure, RunningInfrastructure
from adgn.mcp._shared.resources import read_text_json_typed

if TYPE_CHECKING:
    from adgn.agent.runtime.local_runtime import LocalAgentRuntime

logger = logging.getLogger(__name__)


@dataclass
class RunningAgent:
    """All infrastructure for a running agent (single point of optionality)."""

    running: RunningInfrastructure
    compositor_app: FastAPI
    mode: AgentMode
    local_runtime: LocalAgentRuntime | None  # None for bridge agents


class AgentEntry:
    """Registry entry with lock-protected optional agent infrastructure."""

    def __init__(self):
        self.agent: RunningAgent | None = None
        self.creation_lock = asyncio.Lock()
        self.operation_lock = asyncio.Lock()


async def create_bridge_infrastructure(
    agent_id: AgentID,
    persistence: SQLitePersistence,
    docker_client: DockerClient,
    mcp_config: MCPConfig,
    initial_policy: str | None = None,
):
    """Create RunningInfrastructure for external agent HTTP bridge."""
    builder = MCPInfrastructure(
        agent_id=agent_id, persistence=persistence, docker_client=docker_client, initial_policy=initial_policy
    )

    return await builder.start(mcp_config)


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
        self._agents: defaultdict[AgentID, AgentEntry] = defaultdict(AgentEntry)
        self._notifier: Callable[[str], Awaitable[None]] | None = None

    def set_notifier(self, notifier: Callable[[str], Awaitable[None]]) -> None:
        """Set notifier callback for registry changes.

        The notifier is called with a resource URI when agents are created/deleted.
        """
        self._notifier = notifier

    async def get_or_create_infrastructure(self, agent_id: AgentID) -> tuple[RunningInfrastructure, FastAPI]:
        """Get or create infrastructure for an agent_id (creates bridge agent).

        Returns both infrastructure and app as a tuple for tests and cases where
        both are needed. Use get_compositor_app() if you only need the app, or
        get_infrastructure() if you only need the infrastructure (without creation).
        """
        entry = self._agents[agent_id]

        async with entry.creation_lock:
            if entry.agent is not None:
                return (entry.agent.running, entry.agent.compositor_app)

            logger.info(f"Creating infrastructure for agent_id={agent_id}")
            running = await create_bridge_infrastructure(
                agent_id=agent_id,
                persistence=self.persistence,
                docker_client=self.docker_client,
                mcp_config=self.mcp_config,
                initial_policy=self.initial_policy,
            )

            await running.__aenter__()

            compositor_app: FastAPI = running.compositor.http_app()  # type: ignore[assignment]

            entry.agent = RunningAgent(
                running=running, compositor_app=compositor_app, mode=AgentMode.BRIDGE, local_runtime=None
            )

            logger.info(f"Infrastructure ready for agent_id={agent_id}")
            return (running, compositor_app)

    async def get_compositor_app(self, agent_id: AgentID) -> FastAPI:
        """Get compositor app for an agent_id."""
        _, app = await self.get_or_create_infrastructure(agent_id)
        return app

    def get_running_infrastructure(self, agent_id: AgentID) -> RunningInfrastructure | None:
        """Get running infrastructure if it exists (doesn't create)."""
        entry = self._agents.get(agent_id)
        return entry.agent.running if entry and entry.agent else None

    def known_agents(self) -> list[AgentID]:
        return list(self._agents.keys())

    async def get_infrastructure(self, agent_id: AgentID) -> RunningInfrastructure:
        """Raises KeyError if agent not in registry or not yet initialized."""
        if agent_id not in self._agents:
            raise KeyError(f"Agent {agent_id} not found in registry")
        agent = self._agents[agent_id].agent
        if agent is None:
            raise KeyError(f"Agent {agent_id} infrastructure not yet initialized")
        return agent.running

    def get_agent_mode(self, agent_id: AgentID) -> AgentMode:
        """Raises KeyError if agent not in registry or not yet initialized."""
        if agent_id not in self._agents:
            raise KeyError(f"Agent {agent_id} not found in registry")
        agent = self._agents[agent_id].agent
        if agent is None:
            raise KeyError(f"Agent {agent_id} mode not yet initialized")
        return agent.mode

    def get_local_runtime(self, agent_id: AgentID) -> LocalAgentRuntime | None:
        """Returns None if agent is not local. Raises KeyError if agent not in registry."""
        if agent_id not in self._agents:
            raise KeyError(f"Agent {agent_id} not found in registry")
        agent = self._agents[agent_id].agent
        return agent.local_runtime if agent else None

    def register_local_agent(
        self,
        agent_id: AgentID,
        running: RunningInfrastructure,
        compositor_app: FastAPI,
        local_runtime: LocalAgentRuntime,
    ) -> None:
        self._agents[agent_id].agent = RunningAgent(
            running=running, compositor_app=compositor_app, mode=AgentMode.LOCAL, local_runtime=local_runtime
        )

    async def create_agent(self, agent_id: AgentID) -> RunningInfrastructure:
        """Create and initialize infrastructure for a new agent.

        Returns the running infrastructure for the agent.
        """
        running, _ = await self.get_or_create_infrastructure(agent_id)
        # Notify that agent list changed
        if self._notifier:
            await self._notifier("resource://agents/list")
        return running

    async def ensure_live(self, agent_id: AgentID) -> RunningInfrastructure:
        """Ensure agent infrastructure exists, creating if necessary.

        Returns the running infrastructure for the agent.
        Raises KeyError if agent does not exist in registry.
        """
        if agent_id not in self._agents:
            raise KeyError(f"Agent {agent_id} not found in registry")
        running, _ = await self.get_or_create_infrastructure(agent_id)
        return running

    async def remove_agent(self, agent_id: AgentID) -> None:
        """Remove and clean up agent infrastructure.

        Closes the running infrastructure and removes the agent from the registry.
        """
        if agent_id not in self._agents:
            raise KeyError(f"Agent {agent_id} not found in registry")

        agent = self._agents[agent_id].agent
        if agent is not None:
            await agent.running.close()

        del self._agents[agent_id]

        if self._notifier:
            await self._notifier("resource://agents/list")


async def create_mcp_server_app(auth_tokens_path: Path, registry: InfrastructureRegistry) -> FastAPI:
    """Create token-authenticated MCP server app.

    Routes MCP-over-HTTP requests to per-agent compositor apps based on token.
    """

    class CompositorRoutingMiddleware(BaseHTTPMiddleware):
        """Routes requests to the appropriate agent's compositor app."""

        async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
            agent_id = request.state.agent_id

            compositor_app = await registry.get_compositor_app(agent_id)

            response_started = False
            status_code = 200
            headers = []
            body_parts = []

            async def send(message):
                nonlocal response_started, status_code, headers
                if message["type"] == "http.response.start":
                    response_started = True
                    status_code = message["status"]
                    headers = message.get("headers", [])
                elif message["type"] == "http.response.body":
                    body_parts.append(message.get("body", b""))

            await compositor_app(request.scope, request.receive, send)

            response_headers = {k.decode(): v.decode() for k, v in headers}
            body = b"".join(body_parts)
            return Response(content=body, status_code=status_code, headers=response_headers)

    token_mapping = TokenMapping(auth_tokens_path)
    mcp_app = FastAPI(title="MCP Server")

    # Order matters: routing first, then token auth (outermost middleware runs first)
    mcp_app.add_middleware(CompositorRoutingMiddleware)
    mcp_app.add_middleware(TokenAuthMiddleware, token_mapping=token_mapping)

    return mcp_app


async def create_management_ui_app(registry: InfrastructureRegistry) -> tuple[FastAPI, str]:
    """Create management UI app with WebSocket channels and token authentication.

    Provides web interface for managing approvals, policy, and agent state.
    Uses UITokenAuthMiddleware for simple token-based authentication.

    Exposes agents MCP server at /mcp/agents for external MCP clients.

    Returns:
        Tuple of (FastAPI app, UI token for Bearer authentication)
    """
    ui_token = generate_ui_token()

    ui_app = FastAPI(title="Management UI")

    agents_server = await make_agents_server(registry)
    agents_http_app = agents_server.http_app()
    ui_app.mount("/mcp/agents", agents_http_app)

    ui_app.state.agents_server = agents_server

    ui_app.add_middleware(UITokenAuthMiddleware, expected_token=ui_token)

    @ui_app.websocket("/ws/mcp")
    async def ws_mcp(websocket: WebSocket, agent_id: AgentID):
        """MCP channel - server state and tool calls."""
        await websocket.accept()
        # TODO: Implement MCP channel
        await websocket.send_json({"type": "not_implemented", "message": "MCP channel coming soon"})
        await websocket.close()

    @ui_app.get("/api/agents")
    async def list_agents():
        """List all active agents.

        Delegates to agents MCP server's resource://agents/list.
        """
        async with Client(agents_server) as client:
            agent_list = await read_text_json_typed(client, "resource://agents/list", AgentList)
            return agent_list.model_dump()

    @ui_app.get("/health")
    async def health():
        """Health check endpoint."""
        return {"status": "ok"}

    @ui_app.get("/api/capabilities")
    async def api_capabilities():
        """Report which components are active in MCP bridge mode."""
        return {
            "mode": "mcp_bridge",
            "components": {
                "mcp": True,  # MCP tools available
                "approvals": True,  # Approval/policy management
                "chat": False,  # No chat interface in bridge mode
                "agent_state": False,  # No agent state (external agents)
                "ui": False,  # Minimal UI (just approvals/policy)
            },
        }

    return ui_app, ui_token
