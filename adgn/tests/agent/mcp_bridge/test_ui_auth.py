"""Test UI Token Authentication for Management UI."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastmcp.mcp_config import MCPConfig
import pytest

from adgn.agent.mcp_bridge.auth import UITokenAuthMiddleware, generate_ui_token
from adgn.agent.mcp_bridge.server import InfrastructureRegistry, create_management_ui_app
from adgn.agent.persist.sqlite import SQLitePersistence

# temp_db fixture is provided by conftest.py


@pytest.fixture
async def infrastructure_registry(temp_db: Path, docker_client) -> InfrastructureRegistry:
    """Create infrastructure registry for testing."""
    persistence = SQLitePersistence(temp_db)
    await persistence.ensure_schema()

    return InfrastructureRegistry(
        persistence=persistence, docker_client=docker_client, mcp_config=MCPConfig(mcpServers={}), initial_policy=None
    )


def test_generate_ui_token_from_env(monkeypatch):
    """Test that generate_ui_token reads from ADGN_UI_TOKEN environment variable."""
    expected_token = "test-ui-token-from-env"
    monkeypatch.setenv("ADGN_UI_TOKEN", expected_token)

    token = generate_ui_token()

    assert token == expected_token


def test_generate_ui_token_random(monkeypatch):
    """Test that generate_ui_token generates random token when env var not set."""
    monkeypatch.delenv("ADGN_UI_TOKEN", raising=False)

    token1 = generate_ui_token()
    token2 = generate_ui_token()

    # Tokens should be non-empty strings
    assert isinstance(token1, str)
    assert len(token1) > 0
    assert isinstance(token2, str)
    assert len(token2) > 0

    # Tokens should be different (random)
    assert token1 != token2

    # Tokens should be URL-safe base64 (no special chars except - and _)
    assert all(c.isalnum() or c in "-_" for c in token1)
    assert all(c.isalnum() or c in "-_" for c in token2)


async def test_ui_auth_middleware_valid_token():
    """Test that UITokenAuthMiddleware accepts valid token."""
    expected_token = "valid-ui-token"

    # Create simple FastAPI app with middleware
    app = FastAPI()
    app.add_middleware(UITokenAuthMiddleware, expected_token=expected_token)

    @app.get("/test")
    async def test_endpoint():
        return {"status": "ok"}

    client = TestClient(app)

    # Request with valid token should succeed
    response = client.get("/test", headers={"Authorization": f"Bearer {expected_token}"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_ui_auth_middleware_invalid_token():
    """Test that UITokenAuthMiddleware rejects invalid token."""
    expected_token = "valid-ui-token"

    # Create simple FastAPI app with middleware
    app = FastAPI()
    app.add_middleware(UITokenAuthMiddleware, expected_token=expected_token)

    @app.get("/test")
    async def test_endpoint():
        return {"status": "ok"}

    client = TestClient(app)

    # Request with invalid token should fail
    response = client.get("/test", headers={"Authorization": "Bearer wrong-token"})

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid token"}
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_ui_auth_middleware_missing_token():
    """Test that UITokenAuthMiddleware rejects requests without token."""
    expected_token = "valid-ui-token"

    # Create simple FastAPI app with middleware
    app = FastAPI()
    app.add_middleware(UITokenAuthMiddleware, expected_token=expected_token)

    @app.get("/test")
    async def test_endpoint():
        return {"status": "ok"}

    client = TestClient(app)

    # Request without Authorization header should fail
    response = client.get("/test")

    assert response.status_code == 401
    assert response.json() == {"detail": "Missing Authorization header"}
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_ui_auth_middleware_invalid_header_format():
    """Test that UITokenAuthMiddleware rejects malformed Authorization header."""
    expected_token = "valid-ui-token"

    # Create simple FastAPI app with middleware
    app = FastAPI()
    app.add_middleware(UITokenAuthMiddleware, expected_token=expected_token)

    @app.get("/test")
    async def test_endpoint():
        return {"status": "ok"}

    client = TestClient(app)

    # Test various invalid formats
    invalid_headers = [
        "valid-ui-token",  # Missing "Bearer" prefix
        "Basic valid-ui-token",  # Wrong auth type
        "Bearer",  # Missing token
        "Bearer token1 token2",  # Too many parts
    ]

    for invalid_header in invalid_headers:
        response = client.get("/test", headers={"Authorization": invalid_header})

        assert response.status_code == 401
        assert "Invalid Authorization header format" in response.json()["detail"]
        assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_management_ui_app_requires_token(infrastructure_registry: InfrastructureRegistry, monkeypatch):
    """Test that create_management_ui_app applies token authentication."""
    # Set a fixed token for testing
    test_token = "test-management-ui-token"
    monkeypatch.setenv("ADGN_UI_TOKEN", test_token)

    ui_app, returned_token = await create_management_ui_app(registry=infrastructure_registry)

    # Verify the returned token matches what we set
    assert returned_token == test_token

    client = TestClient(ui_app)

    # Request without token should fail
    response = client.get("/health")
    assert response.status_code == 401

    # Request with valid token should succeed
    response = client.get("/health", headers={"Authorization": f"Bearer {test_token}"})
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    # Request with invalid token should fail
    response = client.get("/health", headers={"Authorization": "Bearer wrong-token"})
    assert response.status_code == 401


async def test_management_ui_app_token_on_all_endpoints(infrastructure_registry: InfrastructureRegistry, monkeypatch):
    """Test that all management UI endpoints require token authentication."""
    test_token = "test-management-ui-token"
    monkeypatch.setenv("ADGN_UI_TOKEN", test_token)

    ui_app, _ = await create_management_ui_app(registry=infrastructure_registry)

    client = TestClient(ui_app)

    # Test various endpoints
    endpoints = ["/health", "/api/agents", "/api/capabilities"]

    for endpoint in endpoints:
        # Without token should fail
        response = client.get(endpoint)
        assert response.status_code == 401, f"Endpoint {endpoint} should require auth"

        # With token should succeed (or at least not fail auth)
        response = client.get(endpoint, headers={"Authorization": f"Bearer {test_token}"})
        assert response.status_code != 401, f"Endpoint {endpoint} should accept valid token"
