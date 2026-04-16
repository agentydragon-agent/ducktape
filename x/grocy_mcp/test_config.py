"""Tests for ServerSettings and AuthentikAuthConfig URL helpers.

Pins the `authentik_token_endpoint()` derivation — the only non-trivial
piece in the auth config.
"""

from __future__ import annotations

import pytest
import pytest_bazel

from x.grocy_mcp.config import ServerSettings


def _settings(issuer: str) -> ServerSettings:
    return ServerSettings(
        oidc_issuer=issuer,
        oidc_client_id="id",
        oidc_client_secret="secret",
        public_base_url="https://grocy-mcp.example.com",
        grocy_url="https://grocy.example.com",
        grocy_proxy_client_id="grocy-proxy-id",
    )


def test_token_endpoint_simple() -> None:
    cfg = _settings("https://auth.allegedly.works/application/o/grocy-mcp/").auth_config()
    assert cfg.authentik_token_endpoint() == "https://auth.allegedly.works/application/o/token/"


def test_token_endpoint_preserves_reverse_proxy_prefix() -> None:
    cfg = _settings("https://example.com/auth/application/o/grocy-mcp/").auth_config()
    assert cfg.authentik_token_endpoint() == "https://example.com/auth/application/o/token/"


def test_token_endpoint_accepts_unterminated_issuer() -> None:
    cfg = _settings("https://auth.allegedly.works/application/o/grocy-mcp").auth_config()
    assert cfg.authentik_token_endpoint() == "https://auth.allegedly.works/application/o/token/"


def test_token_endpoint_rejects_non_authentik_issuer() -> None:
    cfg = _settings("https://keycloak.example.com/realms/grocy-mcp").auth_config()
    with pytest.raises(ValueError, match="Authentik per-provider issuer path"):
        cfg.authentik_token_endpoint()


def test_token_endpoint_rejects_missing_slug() -> None:
    cfg = _settings("https://auth.allegedly.works/application/o/").auth_config()
    with pytest.raises(ValueError, match="Authentik per-provider issuer path"):
        cfg.authentik_token_endpoint()


if __name__ == "__main__":
    pytest_bazel.main()
