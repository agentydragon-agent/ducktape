"""End-to-end integration tests for the approval gate.

Spins up a real FastMCP backend server and a real approval gate HTTP server,
then exercises the full approval workflow using a real MCP client and REST calls.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import jwt as pyjwt
import pytest
import pytest_bazel
import uvicorn
from cryptography.hazmat.primitives.asymmetric import rsa
from fastmcp import FastMCP
from fastmcp.client import Client
from fastmcp.mcp_config import RemoteMCPServer

from approval_gate.app import create_app
from approval_gate.config import Settings
from approval_gate.models import ActionRef
from util.net import pick_free_port

_AGENT_API_KEY = "test-e2e-agent-key"


@asynccontextmanager
async def _serve(app: Any, *, port: int) -> AsyncIterator[None]:
    """Run an ASGI app with uvicorn on the given port; shut it down on exit."""
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    deadline = time.monotonic() + 10.0
    while not server.started:
        if task.done():
            # Uvicorn exited before the port was bound — surface the root cause fast
            # instead of waiting the full 10-second timeout.
            try:
                task.result()
            except Exception as exc:
                raise RuntimeError(f"uvicorn on port {port} exited before starting: {exc}") from exc
            raise RuntimeError(f"uvicorn on port {port} exited before starting (no exception)")
        if time.monotonic() > deadline:
            server.should_exit = True
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            raise TimeoutError(f"server did not start on port {port}")
        await asyncio.sleep(0.02)
    try:
        yield
    finally:
        server.should_exit = True
        await task


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


@pytest.fixture
async def backend_server():
    """Real FastMCP backend with an `echo` tool; yields (base_url, calls_list)."""
    calls: list[dict[str, Any]] = []

    backend = FastMCP("test-backend")

    @backend.tool()
    async def echo(text: str) -> str:
        calls.append({"text": text})
        return f"echoed: {text}"

    port = pick_free_port()
    async with _serve(backend.http_app(path="/mcp"), port=port):
        yield f"http://127.0.0.1:{port}", calls


@pytest.fixture
async def gate(backend_server, tmp_path, mock_jwks_signing_key, admin_jwt):
    """Real approval gate backed by backend_server; yields (gate_url, agent_key, admin_jwt)."""
    backend_url, _ = backend_server
    gate_port = pick_free_port()
    settings = Settings(
        agent_api_key=_AGENT_API_KEY,
        backend=RemoteMCPServer(url=f"{backend_url}/mcp"),
        public_base_url=f"http://127.0.0.1:{gate_port}",
        operator_jwks_url="http://test/jwks",
        db_path=tmp_path / "gate.db",
    )
    with patch("jwt.PyJWKClient.get_signing_key_from_jwt", return_value=mock_jwks_signing_key):
        app = create_app(settings, include_static=False)
        async with _serve(app, port=gate_port):
            yield f"http://127.0.0.1:{gate_port}", _AGENT_API_KEY, admin_jwt


async def _call_tool(gate_url: str, agent_key: str, tool_name: str, args: dict) -> str:
    """Call a tool on the approval gate via MCP; return the action_id from ActionRef."""
    transport = RemoteMCPServer(url=f"{gate_url}/mcp", headers={"Authorization": f"Bearer {agent_key}"}).to_transport()
    async with Client(transport) as client:
        result = await client.call_tool_mcp(tool_name, args)
    assert not result.isError, f"tool call returned error: {result.content}"
    return ActionRef.model_validate_json(result.content[0].text).action_id


async def _wait_for_status(
    gate_url: str, admin_jwt: str, action_id: str, status: str, timeout_secs: float = 5.0
) -> None:
    """Poll /api/actions until action reaches the expected status or timeout."""
    async with asyncio.timeout(timeout_secs):
        while True:
            async with httpx.AsyncClient(base_url=gate_url) as http:
                resp = await http.get("/api/actions", params={"status": status}, headers={"X-Authentik-Jwt": admin_jwt})
            resp.raise_for_status()
            if any(a["id"] == action_id for a in resp.json()["actions"]):
                return
            await asyncio.sleep(0.05)


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_tool_list_wraps_backend_tools(gate):
    """MCP tool list exposes backend tools wrapped with the approval-gate schema envelope."""
    gate_url, agent_key, _ = gate
    transport = RemoteMCPServer(url=f"{gate_url}/mcp", headers={"Authorization": f"Bearer {agent_key}"}).to_transport()
    async with Client(transport) as client:
        tools = await client.list_tools()

    names = [t.name for t in tools]
    assert "echo" in names

    echo = next(t for t in tools if t.name == "echo")
    props = echo.inputSchema["properties"]
    # Envelope fields present at top level
    assert "justification" in props
    assert "session_key" in props
    # Original backend schema nested under `input`
    assert "input" in props
    assert "text" in props["input"]["properties"]


async def test_approve_executes_backend_tool(gate, backend_server):
    """Happy path: tool call queued → operator approves → backend runs → action done."""
    gate_url, agent_key, admin_jwt = gate
    _, backend_calls = backend_server

    action_id = await _call_tool(
        gate_url, agent_key, "echo", {"input": {"text": "hello e2e"}, "justification": "e2e approve"}
    )

    async with httpx.AsyncClient(base_url=gate_url) as http:
        resp = await http.post(f"/api/actions/{action_id}/approve", headers={"X-Authentik-Jwt": admin_jwt})
    assert resp.status_code == 200

    await _wait_for_status(gate_url, admin_jwt, action_id, "done")
    assert backend_calls == [{"text": "hello e2e"}]


async def test_reject_leaves_action_rejected_and_skips_backend(gate, backend_server):
    """Reject path: tool call queued → operator rejects → rejected state, backend not called."""
    gate_url, agent_key, admin_jwt = gate
    _, backend_calls = backend_server

    action_id = await _call_tool(
        gate_url, agent_key, "echo", {"input": {"text": "should not run"}, "justification": "e2e reject"}
    )

    async with httpx.AsyncClient(base_url=gate_url) as http:
        resp = await http.post(
            f"/api/actions/{action_id}/reject",
            json={"reason": "e2e test rejection"},
            headers={"X-Authentik-Jwt": admin_jwt},
        )
    assert resp.status_code == 200

    await _wait_for_status(gate_url, admin_jwt, action_id, "rejected")
    assert backend_calls == []


async def test_auto_approve_predicate_skips_queue(backend_server, tmp_path, mock_jwks_signing_key, admin_jwt):
    """Auto-approve predicate: tool call immediately executes without any operator action."""
    backend_url, backend_calls = backend_server

    predicate_path = tmp_path / "predicate.py"
    predicate_path.write_text(
        "from approval_gate.predicates import Approved\n\ndef decide(tool_name, arguments):\n    return Approved()\n"
    )

    gate_port = pick_free_port()
    settings = Settings(
        agent_api_key=_AGENT_API_KEY,
        backend=RemoteMCPServer(url=f"{backend_url}/mcp"),
        public_base_url=f"http://127.0.0.1:{gate_port}",
        operator_jwks_url="http://test/jwks",
        db_path=tmp_path / "gate_auto.db",
        predicate_path=predicate_path,
    )
    with patch("jwt.PyJWKClient.get_signing_key_from_jwt", return_value=mock_jwks_signing_key):
        app = create_app(settings, include_static=False)
        async with _serve(app, port=gate_port):
            gate_url = f"http://127.0.0.1:{gate_port}"
            action_id = await _call_tool(
                gate_url, _AGENT_API_KEY, "echo", {"input": {"text": "auto"}, "justification": "auto-approve"}
            )
            # No human approval — predicate auto-approved and backend ran
            await _wait_for_status(gate_url, admin_jwt, action_id, "done")

    assert backend_calls == [{"text": "auto"}]


if __name__ == "__main__":
    pytest_bazel.main()
