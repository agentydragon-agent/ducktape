"""Tests for webhook authentication handlers."""

import pytest
from fastapi import Request
from fastapi.security import HTTPAuthorizationCredentials

from ..config import BearerAuth, NoAuth
from .webhook_auth import (
    AuthError,
    BearerAuthHandler,
    NoAuthHandler,
    create_auth_handler,
)


@pytest.fixture
def no_auth_config():
    """Fixture for NoAuth configuration."""
    return NoAuth()


@pytest.fixture
def bearer_auth_config():
    """Fixture for BearerAuth configuration."""
    return BearerAuth(token="test-token")


@pytest.fixture
def no_auth_handler(no_auth_config):
    """Fixture for NoAuthHandler instance."""
    return NoAuthHandler(no_auth_config)


@pytest.fixture
def bearer_auth_handler(bearer_auth_config):
    """Fixture for BearerAuthHandler instance."""
    return BearerAuthHandler(bearer_auth_config)


@pytest.fixture
def mock_request():
    """Fixture for mock Request object."""
    return Request({"type": "http"})


class TestAuthHandlerCreation:
    @pytest.mark.parametrize(
        "config,expected_handler_class",
        [
            ("no_auth_config", NoAuthHandler),
            ("bearer_auth_config", BearerAuthHandler),
        ],
    )
    async def test_create_auth_handler_success(
        self, request, config, expected_handler_class
    ):
        """Test create_auth_handler with valid configurations."""
        config = request.getfixturevalue(config)
        handler = create_auth_handler(config)
        assert isinstance(handler, expected_handler_class)

    async def test_create_auth_handler_unknown_type(self):
        """Test create_auth_handler with unknown configuration type."""
        class UnknownAuthConfig:
            pass

        with pytest.raises(ValueError, match="Unknown authentication type"):
            create_auth_handler(UnknownAuthConfig())


class TestNoAuthHandler:
    async def test_validate_success(self, no_auth_handler, mock_request):
        """Test NoAuthHandler validation always succeeds."""
        # No auth should pass regardless of credentials
        await no_auth_handler.validate(mock_request, None)
        await no_auth_handler.validate(
            mock_request, HTTPAuthorizationCredentials(scheme="any", credentials="any")
        )


class TestBearerAuthHandler:
    async def test_validate_success(self, bearer_auth_handler, mock_request):
        """Test BearerAuthHandler validation with valid credentials."""
        credentials = HTTPAuthorizationCredentials(scheme="bearer", credentials="test-token")
        await bearer_auth_handler.validate(mock_request, credentials)

    async def test_validate_missing_credentials(self, bearer_auth_handler, mock_request):
        """Test BearerAuthHandler validation with missing credentials."""
        with pytest.raises(AuthError, match="Missing Authorization header"):
            await bearer_auth_handler.validate(mock_request, None)

    async def test_validate_wrong_scheme(self, bearer_auth_handler, mock_request):
        """Test BearerAuthHandler validation with wrong scheme."""
        credentials = HTTPAuthorizationCredentials(scheme="basic", credentials="test-token")
        with pytest.raises(AuthError, match="Invalid authentication scheme"):
            await bearer_auth_handler.validate(mock_request, credentials)

    async def test_validate_invalid_token(self, bearer_auth_handler, mock_request):
        """Test BearerAuthHandler validation with invalid token."""
        credentials = HTTPAuthorizationCredentials(scheme="bearer", credentials="wrong-token")
        with pytest.raises(AuthError, match="Invalid token"):
            await bearer_auth_handler.validate(mock_request, credentials)