import sys
import shutil

import pytest
import docker
from contextlib import asynccontextmanager
from typing import AsyncIterator, Tuple
from mcp.server.fastmcp import FastMCP
from adgn.llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn.llm.mcp.testing.typed_stubs import TypedClient
from adgn.llm.mini_codex.mcp_manager import McpManager


def pytest_configure(config):
    # Register custom markers to avoid PytestUnknownMarkWarning
    config.addinivalue_line(
        "markers",
        "requires_docker: test requires Docker Engine (docker.from_env().ping())",
    )
    config.addinivalue_line("markers", "macos: macOS-only test")
    config.addinivalue_line(
        "markers",
        "requires_sandbox_exec: test requires macOS seatbelt sandbox-exec present in PATH",
    )


def pytest_collection_modifyitems(config, items):
    """
    Auto-skip tests:
    - @pytest.mark.macos when not running on macOS
    - @pytest.mark.requires_docker when Docker Engine ping fails (or docker SDK missing)
    """
    # macOS gating
    if sys.platform != "darwin":
        skip_macos = pytest.mark.skip(reason="macOS-only test (macos marker)")
        for item in items:
            if "macos" in item.keywords:
                item.add_marker(skip_macos)

    # Docker gating (SDK is a hard dependency; only skip when ping fails)
    docker_ok = True
    try:
        docker.from_env().ping()
    except Exception:
        docker_ok = False

    if not docker_ok:
        skip_docker = pytest.mark.skip(reason="requires Docker Engine (ping failed)")
        for item in items:
            if "requires_docker" in item.keywords:
                item.add_marker(skip_docker)

    # sandbox-exec gating (implies macOS)
    for item in items:
        if "requires_sandbox_exec" in item.keywords:
            if sys.platform != "darwin":
                item.add_marker(pytest.mark.skip(reason="macOS-only (sandbox-exec)"))
            elif not shutil.which("sandbox-exec"):
                item.add_marker(
                    pytest.mark.skip(reason="sandbox-exec not found on PATH")
                )


@pytest.fixture()
def require_sandbox_exec() -> None:
    """Skip test unless running on macOS with sandbox-exec in PATH.

    Shared fixture for seatbelt/sandboxer/MCP tests that depend on macOS seatbelt.
    """
    if sys.platform != "darwin":
        pytest.skip("macOS-only (sandbox-exec)")
    if not shutil.which("sandbox-exec"):
        pytest.skip("sandbox-exec not found on PATH")


# ---- Shared MCP typed client fixture ----------------------------------------


@pytest.fixture
def make_typed_mcp():
    """Factory that yields (TypedClient, session) for a single in-proc MCP server.

    Usage:
        async with make_typed_mcp(server, "name") as (client, session):
            Args = client.models["tool"].Input
            out = await client.tool(Args(...))
    """

    @asynccontextmanager
    async def _open(
        server: FastMCP, name: str
    ) -> AsyncIterator[Tuple[TypedClient, object]]:
        spec = make_inproc_slot_spec(server)
        async with McpManager({name: spec}) as mcp:
            session = await mcp.get_session(name)
            client = TypedClient.from_server(server, session)
            yield client, session

    return _open
