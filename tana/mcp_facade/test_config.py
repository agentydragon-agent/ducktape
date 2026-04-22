"""Tests for Tana MCP facade settings."""

from __future__ import annotations

import pytest_bazel

from mcp_infra.authentik_auth.auth import AuthentikAuthConfig
from tana.mcp_facade.config import ServerSettings


def test_settings_round_trip() -> None:
    settings = ServerSettings(
        auth=AuthentikAuthConfig(
            oidc_issuer="https://auth.example.com/application/o/tana-mcp-facade/",
            oidc_client_id="id",
            oidc_client_secret="secret",
            public_base_url="https://tana-mcp-facade.example.com",
        ),
        downstream_url="http://tana-mcp.tana-mcp.svc.cluster.local:8263/mcp",
        static_bearer_token="pat",
    )
    assert settings.auth.normalized_public_base_url() == "https://tana-mcp-facade.example.com"


if __name__ == "__main__":
    pytest_bazel.main()
