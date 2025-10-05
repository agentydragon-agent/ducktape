from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import asynccontextmanager, contextmanager
import os
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi.testclient import TestClient
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel
import pytest

from adgn.agent.approvals import ApprovalHub, ApprovalPolicyEngine, ApprovalPolicyHandler
from adgn.agent.mcp_manager import McpManager
from adgn.agent.server.app import create_app
from adgn.mcp.editor_server import make_editor_mcp
from adgn.mcp.inproc_transport import make_inproc_slot_spec
from adgn.mcp.testing.typed_stubs import TypedClient
from adgn.openai_utils.model import FakeOpenAIModel, ResponsesResult
from tests.agent.ws_helpers import (
    collect_payloads_until_finished,
    collect_payloads_until_finished_auto_approve,
    wait_for_accepted,
)

# --- Pytest fixtures (prefer fixtures over cross-importing test modules) ---


@pytest.fixture
def approval_engine() -> ApprovalPolicyEngine:
    return ApprovalPolicyEngine()


@pytest.fixture
def approval_handler(approval_engine: ApprovalPolicyEngine) -> ApprovalPolicyHandler:
    return ApprovalPolicyHandler(approval_engine, ApprovalHub())


# Shared model fixture for live tests that need a reasoning-capable model
@pytest.fixture(scope="session")
def reasoning_model() -> str:
    # Default to gpt-5-nano for fast, reasoning-capable behavior; allow override via env
    return os.environ.get("RESPONSES_TEST_MODEL", "gpt-5-nano")


# assistant_response_factory, tool_call_response_factory, responses_factory
# come from tests.fixtures.responses (registered globally in tests/conftest.py).


# Local factory: construct our Pydantic-only fake client from a sequence of ResponsesResult
@pytest.fixture
def fake_openai_client_factory() -> Callable[[Iterable[ResponsesResult]], FakeOpenAIModel]:
    def _make(outputs: Iterable[ResponsesResult]) -> FakeOpenAIModel:
        return FakeOpenAIModel(list(outputs))

    return _make


# No extra param fixtures here; reuse existing LIVE sentinel infra from tests/llm.


# ---- Shared ContainerOptions fixtures and in-proc docker exec specs ----
# Kept here so all tests can reuse the same settings consistently.


@pytest.fixture
async def empty_mcp() -> McpManager:
    """A real McpManager with zero servers, entered for the test duration."""
    mgr = McpManager({})
    await mgr.__aenter__()
    try:
        yield mgr
    finally:
        await mgr.__aexit__(None, None, None)


@pytest.fixture
def typed_editor_factory(tmp_path: Path, make_typed_mcp):
    """Factory that yields (TypedClient, target_path) for an in-proc editor server."""

    @asynccontextmanager
    async def _open(
        initial_text: str = "x = 1\n",
    ) -> AsyncIterator[tuple[TypedClient, Path]]:
        target = tmp_path / "sample.py"
        target.write_text(initial_text, encoding="utf-8")
        srv = make_editor_mcp(target)
        async with make_typed_mcp(srv, "editor") as (client, _session):
            yield client, target

    return _open


# Provide a shared typed MCP session helper for tests that need a TypedClient
# make_typed_mcp now provided globally in tests/conftest.py


@pytest.fixture
def make_echo_mcp_server() -> Callable[[], FastMCP]:
    """Factory returning a simple echo MCP server producing structured data."""

    def _make() -> FastMCP:
        mcp = FastMCP("echo")

        @mcp.tool()
        def echo(text: str) -> dict[str, Any]:
            return {"ok": True, "echo": text}

        return mcp

    return _make


@pytest.fixture
def make_echo_spec() -> Callable[[], dict[str, Any]]:
    """Return a factory that yields a typed, JSON-serializable inproc spec for echo MCP.

    Using a typed InprocFactorySpec avoids needing TestClient.portal bridging in tests.
    """

    def _spec() -> dict[str, Any]:
        from adgn.agent.runtime.specs import InprocFactorySpec

        return {"echo": InprocFactorySpec(factory="adgn.mcp.echo.server:make_echo_mcp")}

    return _spec


# Helper: create a live agent via HTTP on a TestClient and return its id
@pytest.fixture
def create_live_agent():
    def _create(client, *, specs: dict[str, Any] | None = None) -> str:
        specs = specs or {}
        # Split into typed JSON specs vs runtime slot specs
        typed: dict[str, Any] = {}
        runtime: dict[str, Any] = {}
        for k, v in list(specs.items()):
            if hasattr(v, "open_uninitialized") or hasattr(v, "open"):
                runtime[k] = v
            else:
                typed[k] = v
        # Create agent via API using a preset
        resp = client.post("/api/agents", json={"preset": "default"})
        assert resp.status_code == 200, resp.text
        agent_id = resp.json()["id"]
        # Attach typed specs via HTTP reconfigure, then runtime slots in-process
        if typed:
            # Enforce one format: ALL typed specs must be Pydantic models (McpServerSpec variants).
            if not all(isinstance(v, BaseModel) for v in typed.values()):
                raise AssertionError("Typed MCP specs must be provided as Pydantic models only")
            attach_json: dict[str, Any] = {
                name: spec.model_dump(mode="json")
                for name, spec in typed.items()  # type: ignore[arg-type]
            }
            # Send over HTTP; server rehydrates to typed McpServerSpec
            r = client.patch(f"/api/agents/{agent_id}/mcp", json={"attach": attach_json})
            assert r.status_code == 200, r.text
        if runtime:

            async def _attach_async() -> None:
                reg = client.app.state.registry
                c = reg.get(agent_id)
                assert c is not None
                m = c.mcp
                assert m is not None
                for name, slot in runtime.items():
                    await m.attach_server(name, slot)

            client.portal.call(_attach_async)
        return agent_id

    return _create


@pytest.fixture
def patch_agent_build_client(monkeypatch: pytest.MonkeyPatch):
    """Return a function to patch container.build_client to a provided fake client.

    Keeps model patching independent from agent creation, so tests can opt-in.
    """

    def _patch(fake_model: Any) -> None:
        monkeypatch.setattr("adgn.agent.runtime.container.build_client", lambda *a, **k: fake_model)

    return _patch


@pytest.fixture
def agent_app_client():
    """Yield a (app, client) pair for the UI server with static assets not required.

    Ensures a consistent pattern across tests, avoiding repeated create_app/TestClient boilerplate.
    """
    app = create_app(require_static_assets=False)
    with TestClient(app) as client:
        yield app, client


@pytest.fixture
def make_spy_spec() -> Callable[[list[str]], dict[str, Any]]:
    def _spec(counter: list[str]) -> dict[str, Any]:
        mcp = FastMCP("spy")

        @mcp.tool()
        def echo(text: str) -> dict[str, Any]:
            counter.append(text)
            return {"ok": True, "echo": text}

        return {"spy": make_inproc_slot_spec(mcp)}

    return _spec


# Unified WS session fixture
@pytest.fixture
def ws_session(agent_app_client, create_live_agent, patch_agent_build_client):
    """Factory to open a websocket session for a newly created agent.

    Usage:
        with ws_session(model_client, specs=my_specs) as (client, ws, collect, agent_id):
            ws.send_json({"type": "send", "text": "hi"})
            payloads = collect(limit=100)  # collects until finished

    Args:
        model_client: Fake/Bound OpenAI client used for the agent
        specs: optional MCP specs dict (typed JSON or runtime slot specs)
        wait_accepted: if True, wait for Accepted after connecting
        auto_approve: if True, collector auto-approves approval_pending events
    """

    @contextmanager
    def _open(
        model_client: Any,
        *,
        specs: dict[str, Any] | None = None,
        wait_accepted: bool = True,
        auto_approve: bool = False,
    ):
        app, client = agent_app_client
        patch_agent_build_client(model_client)
        agent_id = create_live_agent(client, specs=specs or {})
        with client.websocket_connect(f"/ws?agent_id={agent_id}") as ws:
            if wait_accepted:
                wait_for_accepted(ws)

            def _collect(limit: int = 200):
                if auto_approve:
                    return collect_payloads_until_finished_auto_approve(ws, limit=limit)
                return collect_payloads_until_finished(ws, limit=limit)

            yield client, ws, _collect, agent_id

    return _open
