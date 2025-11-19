"""Authentication middleware for HTTP MCP Bridge.

Reads Bearer token from Authorization header and maps it to agent_id.
Enables multi-tenancy: different tokens → different agent_ids → isolated infrastructure.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum
import json
import logging
import os
from pathlib import Path
import secrets

from fastapi import HTTPException, Request, Response, status
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from adgn.agent.types import AgentID

logger = logging.getLogger(__name__)


class TokenRole(StrEnum):
    """MCP connection routing roles from token table lookup."""

    HUMAN = "human"  # Routes to agents management server
    AGENT = "agent"  # Routes to agent's compositor


class TokenInfo(BaseModel):
    """Token information from token mapping file."""

    role: TokenRole
    agent_id: AgentID | None = None  # Required for AGENT role, None for HUMAN role


class TokenMapping:
    """Maps Bearer tokens to TokenInfo from a JSON file.

    Supports two file formats:

    New format (with roles):
        {
          "secret-token-123": {"role": "agent", "agent_id": "chatgpt-agent"},
          "secret-token-456": {"role": "agent", "agent_id": "claude-agent"},
          "ui-token-789": {"role": "human"}
        }

    Legacy format (backwards compatible, assumes AGENT role):
        {
          "secret-token-123": "chatgpt-agent",
          "secret-token-456": "claude-agent"
        }
    """

    def __init__(self, path: Path):
        self.path = path
        self._mapping: dict[str, TokenInfo] = {}
        self.reload()

    def reload(self) -> None:
        """Reload mapping from file."""
        if not self.path.exists():
            raise FileNotFoundError(f"Token mapping file not found: {self.path}")

        data = json.loads(self.path.read_text())
        if not isinstance(data, dict):
            raise ValueError("Token mapping must be a JSON object")

        # Parse each token mapping
        mapping: dict[str, TokenInfo] = {}
        for token, value in data.items():
            if not isinstance(token, str):
                raise ValueError(f"Token key must be string: {token}")

            # Handle both legacy format (string) and new format (dict)
            if isinstance(value, str):
                # Legacy format: token -> agent_id (assumes AGENT role)
                mapping[token] = TokenInfo(role=TokenRole.AGENT, agent_id=AgentID(value))
            elif isinstance(value, dict):
                # New format: token -> {role, agent_id?}
                token_info = TokenInfo.model_validate(value)
                # Validate: AGENT role requires agent_id
                if token_info.role == TokenRole.AGENT and token_info.agent_id is None:
                    raise ValueError(f"AGENT role token {token} missing agent_id")
                # Convert agent_id string to AgentID type
                if token_info.agent_id is not None:
                    token_info.agent_id = AgentID(token_info.agent_id)
                mapping[token] = token_info
            else:
                raise ValueError(f"Invalid token mapping value for {token}: {value}")

        self._mapping = mapping
        logger.info(f"Loaded {len(self._mapping)} token mappings from {self.path}")

    def get_token_info(self, token: str) -> TokenInfo | None:
        """Get TokenInfo for a token, or None if not found."""
        return self._mapping.get(token)

    def get_agent_id(self, token: str) -> AgentID | None:
        """Get agent_id for a token, or None if not found.

        Legacy method for backward compatibility. Returns None for HUMAN role tokens.
        """
        token_info = self._mapping.get(token)
        return token_info.agent_id if token_info else None


class TokenAuthMiddleware(BaseHTTPMiddleware):
    """Validates Bearer token and injects token info into request state.

    Adds request.state.token_info and request.state.agent_id for downstream handlers.
    Returns 401 if token is missing or invalid.
    """

    def __init__(self, app, token_mapping: TokenMapping):
        super().__init__(app)
        self.token_mapping = token_mapping

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        # Extract Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing Authorization header",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Parse Bearer token
        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Authorization header format (expected: Bearer <token>)",
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = parts[1]

        # Map token to TokenInfo
        token_info = self.token_mapping.get_token_info(token)
        if token_info is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token", headers={"WWW-Authenticate": "Bearer"}
            )

        # Inject token_info and agent_id into request state
        request.state.token_info = token_info
        request.state.agent_id = token_info.agent_id  # None for HUMAN tokens
        logger.debug(f"Authenticated request: token → role={token_info.role}, agent_id={token_info.agent_id}")

        return await call_next(request)


def generate_ui_token() -> str:
    """Generate UI token for Management UI access.

    Reads from ADGN_UI_TOKEN environment variable if set, otherwise generates a random token.
    The random token is 32 bytes (256 bits) encoded as URL-safe base64 (43 characters).

    Returns:
        UI token string for Bearer authentication
    """
    env_token = os.environ.get("ADGN_UI_TOKEN")
    if env_token:
        logger.info("Using ADGN_UI_TOKEN from environment")
        return env_token

    token = secrets.token_urlsafe(32)
    logger.info("Generated random UI token (set ADGN_UI_TOKEN environment variable to use a fixed token)")
    return token


class UITokenAuthMiddleware(BaseHTTPMiddleware):
    """Validates UI token for Management UI access.

    Simpler than TokenAuthMiddleware - just validates a single token for accessing the management UI.
    No multi-tenancy: all authenticated requests get the same access.
    """

    def __init__(self, app, expected_token: str):
        super().__init__(app)
        self.expected_token = expected_token

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        # Extract Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing Authorization header",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Parse Bearer token
        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Authorization header format (expected: Bearer <token>)",
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = parts[1]

        # Validate token
        if token != self.expected_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token", headers={"WWW-Authenticate": "Bearer"}
            )

        logger.debug("Authenticated UI request")

        return await call_next(request)
