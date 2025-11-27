"""Token authentication and routing for MCP bridge.

Provides:
- Token loading from YAML config
- ASGI-level routing based on bearer token
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

if TYPE_CHECKING:
    from adgn.agent.types import AgentID

logger = logging.getLogger(__name__)

# Default tokens config path
DEFAULT_TOKENS_PATH = Path("~/.config/adgn/tokens.yaml").expanduser()


def load_tokens(
    path: Path | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    """Load tokens from YAML config file.

    Args:
        path: Path to tokens.yaml file. Defaults to ~/.config/adgn/tokens.yaml

    Returns:
        Tuple of (user_tokens, agent_tokens) where:
        - user_tokens: dict mapping token → user_id
        - agent_tokens: dict mapping token → agent_id

    Token file format:
    ```yaml
    users:
      admin: "hex_token_here"

    agents:
      claude-code-1: "hex_token_here"
    ```
    """
    config_path = path or Path(os.getenv("ADGN_TOKENS_PATH", str(DEFAULT_TOKENS_PATH)))

    user_tokens: dict[str, str] = {}
    agent_tokens: dict[str, str] = {}

    if not config_path.exists():
        logger.warning(f"Tokens config not found at {config_path}, using empty tokens")
        return user_tokens, agent_tokens

    with open(config_path) as f:
        data = yaml.safe_load(f) or {}

    # Parse users section: user_id -> token becomes token -> user_id
    users_section = data.get("users", {})
    for user_id, token in users_section.items():
        if token:
            user_tokens[token] = user_id

    # Parse agents section: agent_id -> token becomes token -> agent_id
    agents_section = data.get("agents", {})
    for agent_id, token in agents_section.items():
        if token:
            agent_tokens[token] = agent_id

    logger.info(f"Loaded {len(user_tokens)} user tokens, {len(agent_tokens)} agent tokens")
    return user_tokens, agent_tokens


class TokenRoutingASGI:
    """ASGI app that routes /mcp requests to different MCP servers based on bearer token.

    This is NOT middleware - it's a top-level ASGI app that dispatches to
    completely different ASGI applications based on the token.

    Token routing:
    - User tokens → global user-facing compositor (sees all agents)
    - Agent tokens → that agent's agent-facing compositor (with policy gateway)
    - No token or invalid token → 401 Unauthorized
    """

    def __init__(
        self,
        user_tokens: dict[str, str],  # token → user_id
        agent_tokens: dict[str, "AgentID"],  # token → agent_id
        user_app: ASGIApp,  # ASGI app for user compositor
        agent_apps: dict["AgentID", ASGIApp],  # ASGI apps for agent compositors
    ):
        self.user_tokens = user_tokens
        self.agent_tokens = agent_tokens
        self.user_app = user_app
        self.agent_apps = agent_apps

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            # Passthrough for lifespan, websocket, etc.
            await self.user_app(scope, receive, send)
            return

        # Extract Authorization header
        headers = dict(scope.get("headers", []))
        auth = headers.get(b"authorization", b"").decode()

        if not auth.startswith("Bearer "):
            response = Response("Unauthorized: Bearer token required", status_code=401)
            await response(scope, receive, send)
            return

        token = auth[7:]

        # Route based on token
        if token in self.user_tokens:
            user_id = self.user_tokens[token]
            logger.debug(f"Routing to user compositor for user: {user_id}")
            await self.user_app(scope, receive, send)
        elif token in self.agent_tokens:
            agent_id = self.agent_tokens[token]
            agent_app = self.agent_apps.get(agent_id)
            if agent_app is None:
                logger.warning(f"Agent app not found for agent_id: {agent_id}")
                response = Response(f"Agent not found: {agent_id}", status_code=404)
                await response(scope, receive, send)
                return
            logger.debug(f"Routing to agent compositor for agent: {agent_id}")
            await agent_app(scope, receive, send)
        else:
            response = Response("Invalid token", status_code=401)
            await response(scope, receive, send)
