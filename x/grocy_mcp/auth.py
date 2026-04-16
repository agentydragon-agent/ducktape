"""Per-request token exchange for Grocy calls.

Every generated tool call flows an `httpx` request through
`AuthentikExchangeAuth`, which swaps the caller's upstream Authentik JWT for
a Grocy-proxy-provider-scoped JWT via RFC 7521 jwt-bearer client-credentials
and stamps the resulting token as `Authorization: Bearer ...` on the outgoing
request. This is the same exchange shape the authentik MCP POC uses; see
<x/authentik_mcp_poc/NOTES.md> §5-§6 for why each piece is load-bearing.

The exchanged token is cached keyed on the upstream JWT so that batch
operations (which fire many concurrent Grocy requests under the same MCP user
context) only hit Authentik's token endpoint once instead of N times. The
cache respects `expires_in` from the exchange response with a safety margin.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

import httpx
from fastmcp.server.dependencies import get_access_token

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from x.grocy_mcp.config import ServerSettings

logger = logging.getLogger(__name__)


# Scopes the MCP server requests when exchanging the caller's token for a
# Grocy-proxy-scoped one. NOT a user-facing config knob — each token is
# load-bearing and the wrong combination produces a silent failure mode:
#
#   - `openid` / `email` / `profile`: populate the standard OIDC identity
#     claims that flow into X-Authentik-{Username,Email,Groups} on the
#     outpost's forward-auth hop.
#   - `ak_proxy`: activates Authentik's "Proxy outpost" property mapping,
#     which is what actually writes those headers. Without it the outpost
#     accepts the token but forwards empty identity headers and Grocy's
#     ReverseProxyAuthMiddleware rejects with HTTP 500. Grocy-specific
#     failure mode documented in <x/authentik_mcp_poc/NOTES.md> §6.
#
# If you ever reuse this class for a different Authentik-protected
# backend, audit the destination's auth requirements before changing this.
EXCHANGE_SCOPES = "openid email profile ak_proxy"

# Subtract this from expires_in to avoid using a token right at expiry.
_EXPIRY_SAFETY_MARGIN = 30.0


class AuthentikExchangeAuth(httpx.Auth):
    """httpx Auth that mints a Grocy-scoped JWT per request.

    Per-request, because each tool invocation runs as a different MCP user
    and the minted JWT must carry that user's identity through the outpost's
    property-mapping hop to Grocy's `ReverseProxyAuthMiddleware`.

    The exchanged token is cached keyed on the upstream JWT so that multiple
    concurrent requests within a single batch tool call reuse the same
    exchange instead of each firing their own TLS+POST to Authentik.

    `get_access_token()` reads FastMCP's request-scoped contextvar — same
    mechanism as the POC's `_extract_bearer_token` at
    <x/authentik_mcp_poc/server.py:64>. `OAuthProxy.load_access_token` has
    already swapped the FastMCP JTI reference for the real upstream
    Authentik JWT before the tool handler (and therefore this auth flow)
    runs.
    """

    def __init__(self, settings: ServerSettings, exchange_client: httpx.AsyncClient) -> None:
        self._settings = settings
        # Must be a *separate* client from the one `FastMCP.from_openapi`
        # wraps with this Auth — reusing the Grocy client here would recurse
        # through `async_auth_flow` forever.
        self._exchange_client = exchange_client
        # Cache: upstream_token → (exchanged_token, expires_at_monotonic)
        self._cache: dict[str, tuple[str, float]] = {}
        # Single lock to prevent thundering-herd on cache miss (multiple
        # concurrent requests all missing cache and firing exchanges).
        self._lock = asyncio.Lock()

    async def _get_exchanged_token(self, upstream_token: str) -> str:
        """Return a cached or freshly exchanged Grocy-proxy-scoped token."""
        now = time.monotonic()

        # Fast path: check cache without lock.
        cached = self._cache.get(upstream_token)
        if cached is not None:
            token, expires_at = cached
            if now < expires_at:
                return token

        # Slow path: acquire lock, re-check, then exchange.
        async with self._lock:
            cached = self._cache.get(upstream_token)
            if cached is not None:
                token, expires_at = cached
                if now < expires_at:
                    return token

            response = await self._exchange_client.post(
                self._settings.authentik_token_endpoint(),
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._settings.grocy_proxy_client_id,
                    "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
                    "client_assertion": upstream_token,
                    "scope": EXCHANGE_SCOPES,
                },
            )
            if response.status_code != 200:
                preview = response.text[:500]
                raise RuntimeError(f"Authentik token exchange failed: status={response.status_code} body={preview!r}")
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("access_token"), str):
                raise RuntimeError(f"token exchange response missing access_token: {payload!r}")

            exchanged_token: str = payload["access_token"]
            expires_in = float(payload.get("expires_in", 300))
            expires_at = now + max(expires_in - _EXPIRY_SAFETY_MARGIN, 10.0)
            self._cache[upstream_token] = (exchanged_token, expires_at)
            logger.debug("cached exchanged token (expires_in=%.0fs, effective_ttl=%.0fs)", expires_in, expires_at - now)
            return exchanged_token

    async def async_auth_flow(self, request: httpx.Request) -> AsyncGenerator[httpx.Request, httpx.Response]:
        access = get_access_token()
        if access is None:
            raise RuntimeError("no authenticated access token in request context")
        token = await self._get_exchanged_token(access.token)
        request.headers["Authorization"] = f"Bearer {token}"
        yield request
