"""Tests for oauth_broker.provider."""

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
import pytest_bazel
import respx
from httpx import Response

from oauth_broker.provider import BrokerConfig, GenericOAuth2Provider, ProviderConfig, TokenData, _parse_token_response


@pytest.fixture
def provider_config() -> ProviderConfig:
    return ProviderConfig(
        name="test",
        display_name="Test Provider",
        authorize_url="https://example.com/authorize",
        token_url="https://example.com/token",
        scopes=["scope1", "scope2"],
        redirect_uri="http://localhost:8080/callback/test",
        secret_name="test-tokens",
    )


@pytest.fixture
def provider(provider_config: ProviderConfig) -> GenericOAuth2Provider:
    return GenericOAuth2Provider(provider_config, "test-client-id", "test-client-secret")


def test_build_authorize_url(provider: GenericOAuth2Provider) -> None:
    url = provider.build_authorize_url("test-state")
    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.hostname == "example.com"
    assert parsed.path == "/authorize"
    assert params["response_type"] == ["code"]
    assert params["client_id"] == ["test-client-id"]
    assert params["scope"] == ["scope1 scope2"]
    assert params["state"] == ["test-state"]


def test_generate_state(provider: GenericOAuth2Provider) -> None:
    state1 = provider.generate_state()
    state2 = provider.generate_state()
    assert state1 != state2
    assert len(state1) > 20


@respx.mock
async def test_exchange_code(provider: GenericOAuth2Provider) -> None:
    route = respx.post("https://example.com/token").mock(
        return_value=Response(
            200,
            json={
                "access_token": "access-123",
                "refresh_token": "refresh-456",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": "scope1 scope2",
            },
        )
    )
    token = await provider.exchange_code("auth-code-789")

    assert token.access_token == "access-123"
    assert token.refresh_token == "refresh-456"
    assert token.scope == "scope1 scope2"
    assert token.expires_at > datetime.now(UTC)
    assert route.called


@respx.mock
async def test_refresh_tokens(provider: GenericOAuth2Provider) -> None:
    route = respx.post("https://example.com/token").mock(
        return_value=Response(
            200,
            json={
                "access_token": "new-access-123",
                "refresh_token": "new-refresh-456",
                "expires_in": 3600,
                "scope": "scope1",
            },
        )
    )
    token = await provider.refresh_tokens("old-refresh-token")

    assert token.access_token == "new-access-123"
    assert token.refresh_token == "new-refresh-456"
    assert route.called


def test_needs_refresh_not_yet(provider: GenericOAuth2Provider) -> None:
    token = TokenData(access_token="a", refresh_token="r", expires_at=datetime.now(UTC) + timedelta(days=15), scope="s")
    assert not provider.needs_refresh(token)


def test_needs_refresh_soon(provider: GenericOAuth2Provider) -> None:
    token = TokenData(
        access_token="a", refresh_token="r", expires_at=datetime.now(UTC) + timedelta(minutes=30), scope="s"
    )
    assert provider.needs_refresh(token)


def test_needs_refresh_expired(provider: GenericOAuth2Provider) -> None:
    token = TokenData(access_token="a", refresh_token="r", expires_at=datetime.now(UTC) - timedelta(hours=1), scope="s")
    assert provider.needs_refresh(token)


def test_parse_token_response() -> None:
    data = {"access_token": "at", "refresh_token": "rt", "token_type": "Bearer", "expires_in": 7200, "scope": "read"}
    token = _parse_token_response(data)
    assert token.access_token == "at"
    assert token.refresh_token == "rt"
    assert token.expires_at > datetime.now(UTC)


def test_broker_config_from_json() -> None:
    json_str = """{
        "target_namespace": "test-ns",
        "providers": [{
            "name": "test",
            "display_name": "Test",
            "authorize_url": "https://example.com/auth",
            "token_url": "https://example.com/token",
            "scopes": ["a"],
            "redirect_uri": "http://localhost/callback/test",
            "secret_name": "test-tokens"
        }]
    }"""
    config = BrokerConfig.model_validate_json(json_str)
    assert config.target_namespace == "test-ns"
    assert len(config.providers) == 1
    assert config.providers[0].name == "test"
    assert config.providers[0].secret_name == "test-tokens"


if __name__ == "__main__":
    pytest_bazel.main()
