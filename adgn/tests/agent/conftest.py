from __future__ import annotations

from collections.abc import Callable, Iterable
import os
from typing import Any, AsyncIterator, Tuple
from pathlib import Path
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP
from adgn.openai_utils.model import (
    ResponsesResult,
    FakeOpenAIModel,
)
import pytest

from adgn.agent.mcp_manager import McpManager
from adgn.mcp.testing.typed_stubs import TypedClient
from adgn.mcp.editor_server import make_editor_mcp
from adgn.mcp.inproc_transport import make_inproc_slot_spec
from adgn.agent.approvals import (
    ApprovalPolicyEngine,
    ApprovalPolicyHandler,
    ApprovalHub,
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
def fake_openai_client_factory() -> Callable[
    [Iterable[ResponsesResult]], FakeOpenAIModel
]:
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
    ) -> AsyncIterator[Tuple[TypedClient, Path]]:
        target = tmp_path / "sample.py"
        target.write_text(initial_text, encoding="utf-8")
        srv = make_editor_mcp(target)
        async with make_typed_mcp(srv, "editor") as (client, _session):
            yield client, target

    return _open


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
def make_echo_spec(make_echo_mcp_server) -> Callable[[], dict[str, Any]]:
    def _spec() -> dict[str, Any]:
        return {"echo": make_inproc_slot_spec(make_echo_mcp_server())}

    return _spec


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
