"""Tests for oauth_broker.refresh."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_bazel

from oauth_broker.provider import GenericOAuth2Provider, ProviderConfig, TokenData
from oauth_broker.refresh import token_refresh_loop


@pytest.fixture
def provider() -> GenericOAuth2Provider:
    return GenericOAuth2Provider(
        ProviderConfig(
            name="test",
            display_name="Test Provider",
            authorize_url="https://example.com/authorize",
            token_url="https://example.com/token",
            scopes=["daily"],
            redirect_uri="https://example.com/callback/test",
            secret_name="test-tokens",
            refresh_margin_seconds=3600,
        ),
        client_id="test-id",
        client_secret="test-secret",
    )


def _make_token(*, hours_until_expiry: float) -> TokenData:
    return TokenData(
        access_token="old-access",
        refresh_token="old-refresh",
        expires_at=datetime.now(UTC) + timedelta(hours=hours_until_expiry),
        scope="daily",
    )


def _make_refreshed_token() -> TokenData:
    return TokenData(
        access_token="new-access",
        refresh_token="new-refresh",
        expires_at=datetime.now(UTC) + timedelta(days=30),
        scope="daily",
    )


async def _run_loop_briefly(
    providers: dict[str, GenericOAuth2Provider], k8s_writer: AsyncMock, namespace: str, sleep: float = 0.05
) -> None:
    task = asyncio.create_task(token_refresh_loop(providers, k8s_writer, namespace, check_interval=0))
    await asyncio.sleep(sleep)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_refresh_loop_refreshes_expiring_token(provider: GenericOAuth2Provider) -> None:
    expiring_token = _make_token(hours_until_expiry=0.5)
    refreshed_token = _make_refreshed_token()

    mock_writer = AsyncMock()
    mock_writer.read_token.return_value = expiring_token

    with patch.object(provider, "refresh_tokens", return_value=refreshed_token):
        await _run_loop_briefly({"test": provider}, mock_writer, "test-ns")

    mock_writer.read_token.assert_called_with("test-tokens", "test-ns")
    mock_writer.write_token.assert_called_with("test-tokens", "test-ns", refreshed_token, annotations=None)


async def test_refresh_loop_skips_fresh_token(provider: GenericOAuth2Provider) -> None:
    fresh_token = _make_token(hours_until_expiry=720)

    mock_writer = AsyncMock()
    mock_writer.read_token.return_value = fresh_token

    with patch.object(provider, "refresh_tokens") as mock_refresh:
        await _run_loop_briefly({"test": provider}, mock_writer, "test-ns")

    mock_refresh.assert_not_called()
    mock_writer.write_token.assert_not_called()


async def test_refresh_loop_skips_unconnected_provider(provider: GenericOAuth2Provider) -> None:
    mock_writer = AsyncMock()
    mock_writer.read_token.return_value = None

    with patch.object(provider, "refresh_tokens") as mock_refresh:
        await _run_loop_briefly({"test": provider}, mock_writer, "test-ns")

    mock_refresh.assert_not_called()


async def test_refresh_loop_continues_on_error(provider: GenericOAuth2Provider) -> None:
    expiring_token = _make_token(hours_until_expiry=0.5)

    mock_writer = AsyncMock()
    mock_writer.read_token.return_value = expiring_token

    call_count = 0

    async def failing_refresh(refresh_token: str) -> TokenData:
        nonlocal call_count
        call_count += 1
        raise RuntimeError("network error")

    with patch.object(provider, "refresh_tokens", side_effect=failing_refresh):
        await _run_loop_briefly({"test": provider}, mock_writer, "test-ns", sleep=0.1)

    assert call_count >= 2
    mock_writer.write_token.assert_not_called()


if __name__ == "__main__":
    pytest_bazel.main()
