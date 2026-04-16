"""Tests for AuthentikAuthConfig and AuthentikExchangeAuth."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest
import pytest_bazel
from authlib.oauth2.rfc6749.wrappers import OAuth2Token

from mcp_infra.authentik_auth.auth import _EXPIRY_LEEWAY, AuthentikAuthConfig, AuthentikExchangeAuth

# ── AuthentikAuthConfig tests ─────────────────────────────────────────────


def _config(issuer: str = "https://auth.example.com/application/o/test/", **kwargs: object) -> AuthentikAuthConfig:
    return AuthentikAuthConfig(
        oidc_issuer=issuer,
        oidc_client_id="id",
        oidc_client_secret="secret",
        public_base_url="https://mcp.example.com",
        **kwargs,
    )


def test_token_endpoint_simple() -> None:
    assert _config().authentik_token_endpoint() == "https://auth.example.com/application/o/token/"


def test_token_endpoint_preserves_reverse_proxy_prefix() -> None:
    cfg = _config("https://example.com/auth/application/o/test/")
    assert cfg.authentik_token_endpoint() == "https://example.com/auth/application/o/token/"


def test_token_endpoint_accepts_unterminated_issuer() -> None:
    cfg = _config("https://auth.example.com/application/o/test")
    assert cfg.authentik_token_endpoint() == "https://auth.example.com/application/o/token/"


def test_token_endpoint_rejects_non_authentik_issuer() -> None:
    with pytest.raises(ValueError, match="Authentik per-provider issuer path"):
        _config("https://keycloak.example.com/realms/test").authentik_token_endpoint()


def test_token_endpoint_rejects_missing_slug() -> None:
    with pytest.raises(ValueError, match="Authentik per-provider issuer path"):
        _config("https://auth.example.com/application/o/").authentik_token_endpoint()


def test_normalized_public_base_url_strips_trailing_slash() -> None:
    cfg = _config(public_base_url="https://mcp.example.com/")
    assert cfg.normalized_public_base_url() == "https://mcp.example.com"


def test_proxy_client_id_optional() -> None:
    cfg = _config()
    assert cfg.proxy_client_id is None


# ── AuthentikExchangeAuth tests ───────────────────────────────────────────


def _exchange_config() -> AuthentikAuthConfig:
    return _config(proxy_client_id="proxy-id")


def test_exchange_auth_requires_proxy_client_id() -> None:
    with pytest.raises(ValueError, match="proxy_client_id is required"):
        AuthentikExchangeAuth(_config())


async def test_exchange_auth_fetches_and_caches_token() -> None:
    auth = AuthentikExchangeAuth(_exchange_config())
    mock_token = OAuth2Token({"access_token": "exchanged-jwt", "expires_in": 3600, "token_type": "bearer"})

    with patch.object(auth._exchange_client, "fetch_token", new_callable=AsyncMock, return_value=mock_token) as fetch:
        # First call: cache miss → fetch.
        token = await auth._get_exchanged_token("upstream-jwt-1")
        assert token == "exchanged-jwt"
        assert fetch.call_count == 1

        # Second call with same upstream token: cache hit → no fetch.
        token = await auth._get_exchanged_token("upstream-jwt-1")
        assert token == "exchanged-jwt"
        assert fetch.call_count == 1

        # Different upstream token: cache miss → fetch again.
        mock_token2 = OAuth2Token({"access_token": "exchanged-jwt-2", "expires_in": 3600, "token_type": "bearer"})
        fetch.return_value = mock_token2
        token = await auth._get_exchanged_token("upstream-jwt-2")
        assert token == "exchanged-jwt-2"
        assert fetch.call_count == 2

    await auth.aclose()


async def test_exchange_auth_refetches_expired_token() -> None:
    auth = AuthentikExchangeAuth(_exchange_config())

    # Token that expires immediately (expires_at in the past).
    expired_token = OAuth2Token({"access_token": "old", "expires_at": int(time.time()) - 1, "token_type": "bearer"})
    fresh_token = OAuth2Token({"access_token": "fresh", "expires_in": 3600, "token_type": "bearer"})

    with patch.object(auth._exchange_client, "fetch_token", new_callable=AsyncMock) as fetch:
        fetch.return_value = expired_token
        token = await auth._get_exchanged_token("upstream")
        assert token == "old"
        assert fetch.call_count == 1

        # Token is expired → should re-fetch.
        fetch.return_value = fresh_token
        token = await auth._get_exchanged_token("upstream")
        assert token == "fresh"
        assert fetch.call_count == 2

    await auth.aclose()


async def test_exchange_auth_respects_leeway() -> None:
    auth = AuthentikExchangeAuth(_exchange_config())

    # Token that expires within the leeway window — should be treated as expired.
    almost_expired = OAuth2Token(
        {"access_token": "almost", "expires_at": int(time.time()) + _EXPIRY_LEEWAY - 1, "token_type": "bearer"}
    )
    fresh = OAuth2Token({"access_token": "fresh", "expires_in": 3600, "token_type": "bearer"})

    with patch.object(auth._exchange_client, "fetch_token", new_callable=AsyncMock) as fetch:
        fetch.return_value = almost_expired
        await auth._get_exchanged_token("upstream")

        fetch.return_value = fresh
        token = await auth._get_exchanged_token("upstream")
        assert token == "fresh"
        assert fetch.call_count == 2

    await auth.aclose()


if __name__ == "__main__":
    pytest_bazel.main()
