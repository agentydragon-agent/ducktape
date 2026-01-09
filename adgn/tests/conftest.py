from __future__ import annotations

import os
import platform
from contextlib import asynccontextmanager, suppress

import docker  # Only used for pytest_runtest_setup health check (sync hook)
import pytest
from fastmcp.client import Client
from fastmcp.server import FastMCP
from openai import AsyncOpenAI

from mcp_infra.compositor.server import Compositor
from mcp_infra.exec.docker.server import ContainerExecServer
from mcp_infra.mcp_types import McpServerSpecs
from mcp_infra.notifications.buffer import NotificationsBuffer
from mcp_infra.prefix import MCPMountPrefix
from mcp_infra.testing.fixtures import make_container_opts

# Register shared fixture modules for parallel workers and subset runs
pytest_plugins = (
    "tests.support.responses",  # openai_client_param fixture
    "mcp_infra.testing.fixtures",  # Shared mcp_infra fixtures
    "agent_core_testing.fixtures",  # Core agent fixtures (make_step_runner, reasoning_model, responses_factory, etc.)
    "pytest_asyncio",  # Ensure async fixtures work in worker processes
)


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("adgn")
    group.addoption(
        "--trace-ws", action="store_true", default=True, help="Emit detailed WS traces during tests (default: on)"
    )
    group.addoption(
        "--no-trace-ws", action="store_true", default=False, help="Disable WS traces added by the test helpers"
    )


def pytest_configure(config: pytest.Config) -> None:
    # Default: tracing ON unless explicitly disabled by --no-trace-ws
    if config.getoption("--no-trace-ws"):
        os.environ["ADGN_TEST_TRACE_WS"] = "0"
    else:
        os.environ["ADGN_TEST_TRACE_WS"] = "1"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        if item.get_closest_marker("requires_sandbox_exec") is not None:
            item.add_marker(pytest.mark.macos)


def pytest_runtest_setup(item: pytest.Item) -> None:
    if item.get_closest_marker("requires_sandbox_exec") is not None and platform.system() != "Darwin":
        pytest.skip("seatbelt sandbox tests require macOS (sandbox-exec unavailable)")
    if item.get_closest_marker("macos") is not None and platform.system() != "Darwin":
        pytest.skip("macOS-only test")
    if item.get_closest_marker("requires_docker") is None:
        return
    try:
        client = docker.from_env()
        client.ping()
    except docker.errors.DockerException as exc:
        pytest.skip(f"Docker not available: {exc}")
    else:
        with suppress(Exception):
            client.close()


async def _mount_servers(comp: Compositor, servers: McpServerSpecs) -> None:
    """Mount all servers from McpServerSpecs dict onto a compositor."""
    for name, srv in servers.items():
        if not isinstance(srv, FastMCP):
            raise TypeError(f"invalid server for {name!r}: {type(srv).__name__}")
        await comp.mount_inproc(MCPMountPrefix(name), srv)


@pytest.fixture
async def mcp_client_echo(make_compositor, echo_spec):
    """Plain MCP client with echo server (no policy gateway)."""
    async with make_compositor(echo_spec) as (client, _comp):
        yield client


@pytest.fixture
async def mcp_client_box(docker_exec_server_py312slim, compositor, compositor_client):
    """MCP client with box Docker exec server (no policy gateway)."""
    await compositor.mount_inproc(MCPMountPrefix("box"), docker_exec_server_py312slim)
    return compositor_client


@pytest.fixture
def make_buffered_client():
    """Async helper to open a Compositor + Client with NotificationsBuffer."""

    @asynccontextmanager
    async def _open(servers: McpServerSpecs):
        async with Compositor(version="1.0.0-test") as comp:
            await _mount_servers(comp, servers)
            buf = NotificationsBuffer(compositor=comp)
            async with Client(comp, message_handler=buf.handler) as sess:
                yield sess, comp, buf

    return _open


@pytest.fixture
async def docker_exec_server_py312slim(async_docker_client):
    """Canonical Docker exec server using python:3.12-slim image."""
    return ContainerExecServer(async_docker_client, make_container_opts("python:3.12-slim"))


@pytest.fixture
async def typed_docker_client(make_typed_mcp, docker_exec_server_py312slim):
    """Typed MCP client for docker exec server with python:3.12-slim."""
    async with make_typed_mcp(docker_exec_server_py312slim) as (client, session):
        yield client, session


@pytest.fixture
def live_openai(request):
    """Provide a live AsyncOpenAI client for tests marked with `live_openai_api`."""
    if request.node.get_closest_marker("live_openai_api") is not None:
        if not os.getenv("OPENAI_API_KEY"):
            pytest.skip("OPENAI_API_KEY not set; skipping live OpenAI test")
        return AsyncOpenAI()

    class _Noop:
        pass

    return _Noop()


@pytest.fixture
def require_sandbox_exec():
    """Gate shell sandbox tests to supported platforms."""
    if platform.system() != "Darwin":
        pytest.skip("sandboxer tests require macOS host")
    return True


@pytest.fixture
def echo_spec(make_simple_mcp) -> McpServerSpecs:
    """In-proc FastMCP server spec for echo tests."""
    return {"echo": make_simple_mcp}
