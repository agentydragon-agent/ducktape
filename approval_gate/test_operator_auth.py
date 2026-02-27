"""Tests for operator API authentication boundaries.

Verifies that the agent bearer token cannot reach operator endpoints, while a
valid Authentik admin JWT can.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import httpx
import jwt as pyjwt
import pytest
import pytest_bazel
from cryptography.hazmat.primitives.asymmetric import rsa
from fastmcp.mcp_config import RemoteMCPServer
from httpx import ASGITransport

from approval_gate.app import create_app
from approval_gate.config import Settings
from approval_gate.models import Action, PendingState, ToolCall
from approval_gate.proxy_server import ApprovalGateServer

_AGENT_API_KEY = "test-agent-bearer-key"
_ACTION_ID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def rsa_private_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def admin_jwt(rsa_private_key):
    return pyjwt.encode({"sub": "admin", "groups": ["authentik Admins"]}, rsa_private_key, algorithm="RS256")


@pytest.fixture
def mock_jwks_signing_key(rsa_private_key):
    key = MagicMock()
    key.key = rsa_private_key.public_key()
    return key


@asynccontextmanager
async def _stub_lifespan(self, app):
    yield


async def _stub_decide(self, action_id, decision):
    return Action(
        id=action_id,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        call=ToolCall(tool_name="echo", arguments={}),
        justification="test",
        session_key=None,
        state=PendingState(),
    )


@pytest.fixture
async def app(tmp_path, mock_jwks_signing_key):
    settings = Settings(
        agent_api_key=_AGENT_API_KEY,
        backend=RemoteMCPServer(url="http://localhost:0/mcp"),
        public_base_url="http://test",
        operator_jwks_url="http://test/jwks",
        db_path=tmp_path / "test.db",
    )
    with (
        patch.object(ApprovalGateServer, "_lifespan", _stub_lifespan),
        patch.object(ApprovalGateServer, "decide", _stub_decide),
        patch("jwt.PyJWKClient.get_signing_key_from_jwt", return_value=mock_jwks_signing_key),
    ):
        the_app = create_app(settings, include_static=False)
        async with the_app.router.lifespan_context(the_app):
            yield the_app


async def test_bearer_token_rejected_on_approve(app):
    """Agent bearer token must be rejected (403) on approve endpoint."""
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/actions/{_ACTION_ID}/approve", headers={"Authorization": f"Bearer {_AGENT_API_KEY}"}
        )
    assert response.status_code == 403


async def test_bearer_token_rejected_on_reject(app):
    """Agent bearer token must be rejected (403) on reject endpoint."""
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/actions/{_ACTION_ID}/reject", headers={"Authorization": f"Bearer {_AGENT_API_KEY}"}
        )
    assert response.status_code == 403


async def test_admin_jwt_accepted_on_approve(app, admin_jwt):
    """Valid Authentik admin JWT must be accepted (200) on approve endpoint."""
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/actions/{_ACTION_ID}/approve", headers={"X-Authentik-Jwt": admin_jwt})
    assert response.status_code == 200


async def test_admin_jwt_accepted_on_reject(app, admin_jwt):
    """Valid Authentik admin JWT must be accepted (200) on reject endpoint."""
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/actions/{_ACTION_ID}/reject", headers={"X-Authentik-Jwt": admin_jwt})
    assert response.status_code == 200


if __name__ == "__main__":
    pytest_bazel.main()
