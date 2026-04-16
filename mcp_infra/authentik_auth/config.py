"""Shared configuration for Authentik-backed MCP servers.

Provides `AuthentikAuthConfig`, a plain dataclass that captures the auth-only
fields needed to wire OIDCProxy + JWTVerifier and perform JWT-bearer token
exchanges against an Authentik proxy provider outpost.

Each MCP server composes this into its own `BaseSettings` and constructs it
from env vars — no inheritance required.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse


@dataclass(frozen=True)
class AuthentikAuthConfig:
    """Auth-only config for an Authentik-backed MCP server.

    Fields map 1:1 to what OIDCProxy and AuthentikExchangeAuth need.
    """

    oidc_issuer: str
    oidc_client_id: str
    oidc_client_secret: str
    public_base_url: str
    proxy_client_id: str
    exchange_timeout: float = 10.0

    def normalized_public_base_url(self) -> str:
        return self.public_base_url.rstrip("/")

    def normalized_issuer(self) -> str:
        return self.oidc_issuer.rstrip("/")

    def authentik_token_endpoint(self) -> str:
        """Global Authentik `/application/o/token/` URL derived from `oidc_issuer`.

        Strips the trailing provider slug, preserving any reverse-proxy path
        prefix before `/application/o/`.
        """
        parsed = urlparse(self.oidc_issuer.rstrip("/"))
        prefix, marker, provider_slug = parsed.path.rpartition("/application/o/")
        if not marker or not provider_slug or "/" in provider_slug:
            raise ValueError(
                "oidc_issuer must end in an Authentik per-provider issuer path "
                f"like `.../application/o/<slug>/`; got {self.oidc_issuer!r}"
            )
        return urlunparse(parsed._replace(path=f"{prefix}{marker}token/"))
