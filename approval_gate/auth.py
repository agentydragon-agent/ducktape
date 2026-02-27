"""Shared Authentik JWT authentication for the approval gate.

Both the operator UI router and the operator REST API router use this.
A single PyJWKClient is created in app.py and injected via closure.
"""

from __future__ import annotations

import asyncio
import logging

import jwt
from fastapi import HTTPException, Request
from jwt import InvalidTokenError, PyJWKClient, PyJWKClientConnectionError, PyJWKClientError

_AUTHENTIK_ADMIN_GROUP = "authentik Admins"

logger = logging.getLogger(__name__)


async def check_authentik_admin(jwks_client: PyJWKClient, token: str) -> None:
    """Verify JWT and admin group membership; raise HTTPException on failure.

    Usable from both FastAPI dependencies and raw ASGI wrappers.
    """
    if not token:
        raise HTTPException(status_code=403, detail="Not authenticated")
    try:
        signing_key = await asyncio.to_thread(jwks_client.get_signing_key_from_jwt, token)
        claims: dict = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"],
            options={"verify_aud": False},
        )
    except InvalidTokenError as exc:
        logger.warning("JWT verification failed: %s", exc)
        raise HTTPException(status_code=403, detail="Invalid token")
    except PyJWKClientConnectionError as exc:
        logger.error("Cannot reach JWKS endpoint: %s", exc)
        raise HTTPException(status_code=503, detail="Authentication service unavailable")
    except PyJWKClientError as exc:
        logger.warning("JWKS key lookup failed: %s", exc)
        raise HTTPException(status_code=403, detail="Invalid token")
    groups: list = claims.get("groups", [])
    if _AUTHENTIK_ADMIN_GROUP not in groups:
        raise HTTPException(status_code=403, detail="Insufficient privileges")


def make_authentik_auth_dep(jwks_client: PyJWKClient):
    """Return a FastAPI dependency that enforces Authentik JWT + admin group membership."""

    async def _require_auth(request: Request) -> None:
        token = request.headers.get("X-Authentik-Jwt", "")
        await check_authentik_admin(jwks_client, token)

    return _require_auth
