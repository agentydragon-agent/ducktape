"""Authentication middleware for HTTP MCP Bridge.

Reads Bearer token from Authorization header and maps it to agent_id.
Enables multi-tenancy: different tokens → different agent_ids → isolated infrastructure.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Awaitable, Callable

from fastapi import HTTPException, Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class TokenMapping:
    """Maps Bearer tokens to agent_ids from a JSON file.

    File format:
        {
          "secret-token-123": "chatgpt-agent",
          "secret-token-456": "claude-agent"
        }
    """

    def __init__(self, path: Path):
        self.path = path
        self._mapping: dict[str, str] = {}
        self.reload()

    def reload(self) -> None:
        """Reload mapping from file."""
        if not self.path.exists():
            logger.warning(f"Token mapping file not found: {self.path}")
            self._mapping = {}
            return

        try:
            data = json.loads(self.path.read_text())
            if not isinstance(data, dict):
                raise ValueError("Token mapping must be a JSON object")

            # Validate all values are strings
            for token, agent_id in data.items():
                if not isinstance(token, str) or not isinstance(agent_id, str):
                    raise ValueError(f"Invalid mapping: {token} -> {agent_id}")

            self._mapping = data
            logger.info(f"Loaded {len(self._mapping)} token mappings from {self.path}")
        except Exception as e:
            logger.error(f"Failed to load token mapping from {self.path}: {e}")
            self._mapping = {}

    def get_agent_id(self, token: str) -> str | None:
        """Get agent_id for a token, or None if not found."""
        return self._mapping.get(token)


class TokenAuthMiddleware(BaseHTTPMiddleware):
    """Validates Bearer token and injects agent_id into request state.

    Adds request.state.agent_id for downstream handlers to use.
    Returns 401 if token is missing or invalid.
    """

    def __init__(self, app, token_mapping: TokenMapping):
        super().__init__(app)
        self.token_mapping = token_mapping

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
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

        # Map token to agent_id
        agent_id = self.token_mapping.get_agent_id(token)
        if agent_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Inject agent_id into request state
        request.state.agent_id = agent_id
        logger.debug(f"Authenticated request: token → agent_id={agent_id}")

        return await call_next(request)
