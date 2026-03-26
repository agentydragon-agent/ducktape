from __future__ import annotations

from pathlib import Path

import pytest
import pytest_bazel
from fastmcp.client import Client

from mcp_infra.constants import WORKING_DIR
from mcp_infra.exec.docker.container_session import AlwaysSetTo, DefaultValue, ModelChooses
from mcp_infra.exec.docker.server import ContainerExecServer
from mcp_infra.exec.models import Exited, TimedOut, make_exec_input
from mcp_infra.testing.fixtures import make_container_opts


@pytest.fixture
async def typed_docker_client(make_typed_mcp, docker_exec_server):
    """Typed MCP client for docker exec server with debian-slim.

    Yields (TypedClient, session) tuple for direct use in tests.
    """
    async with make_typed_mcp(docker_exec_server) as (client, session):
        yield client, session


# All tests below require structuredContent and call via the typed client


async def test_hello_world(typed_docker_client) -> None:
    client, session = typed_docker_client
    tools = await session.list_tools()
    names = {t.name for t in tools}
    assert "exec" in names

    res = await client.exec(make_exec_input(["/bin/echo", "hello"]))
    assert isinstance(res.exit, Exited)
    assert res.exit.exit_code == 0
    assert isinstance(res.stdout, str)  # Short output should not be truncated
    assert "hello" in (res.stdout or "")


async def test_stderr_and_exit_code(typed_docker_client) -> None:
    client, _session = typed_docker_client
    res = await client.exec(make_exec_input(["sh", "-lc", "echo err 1>&2; exit 3"]))
    expected_err_exit = 3
    assert isinstance(res.exit, Exited)
    assert res.exit.exit_code == expected_err_exit
    assert isinstance(res.stderr, str)  # Short error should not be truncated
    assert "err" in (res.stderr or "")


async def test_timeout_flag(typed_docker_client) -> None:
    client, _session = typed_docker_client
    res = await client.exec(make_exec_input(["sh", "-lc", "sleep 5"], timeout_ms=500))
    assert isinstance(res.exit, TimedOut)


# -- CwdPolicy tests: verify each mode runs commands in the expected directory --


@pytest.fixture
def make_cwd_server(async_docker_client, debian_slim_image):
    """Factory for ContainerExecServer with a specific cwd_policy."""

    def _factory(cwd_policy):
        opts = make_container_opts(debian_slim_image)
        return ContainerExecServer(
            async_docker_client, opts, cwd_policy=cwd_policy, allow_user_field=False, allow_env_field=False
        )

    return _factory


async def test_cwd_default_value(make_cwd_server) -> None:
    """DefaultValue: command runs in the default cwd when cwd is omitted."""
    server = make_cwd_server(DefaultValue(value=WORKING_DIR))
    async with Client(server) as c:
        result = await c.call_tool("exec", {"cmd": ["pwd"], "timeout_ms": 10000})
        text = result.content[0].text if result.content else ""
        assert str(WORKING_DIR) in text


async def test_cwd_default_value_override(make_cwd_server) -> None:
    """DefaultValue: model can override cwd."""
    server = make_cwd_server(DefaultValue(value=WORKING_DIR))
    async with Client(server) as c:
        result = await c.call_tool("exec", {"cmd": ["pwd"], "cwd": "/tmp", "timeout_ms": 10000})
        text = result.content[0].text if result.content else ""
        assert "/tmp" in text


async def test_cwd_always_set_to(make_cwd_server) -> None:
    """AlwaysSetTo: command always runs in the fixed cwd, field hidden from schema."""
    server = make_cwd_server(AlwaysSetTo(value=Path("/tmp")))
    async with Client(server) as c:
        tools = await c.list_tools()
        exec_tool = next(t for t in tools if t.name == "exec")
        assert "cwd" not in exec_tool.inputSchema.get("properties", {})

        result = await c.call_tool("exec", {"cmd": ["pwd"], "timeout_ms": 10000})
        text = result.content[0].text if result.content else ""
        assert "/tmp" in text


async def test_cwd_model_chooses(make_cwd_server) -> None:
    """ModelChooses: cwd is required in the schema, model must provide it."""
    server = make_cwd_server(ModelChooses())
    async with Client(server) as c:
        tools = await c.list_tools()
        exec_tool = next(t for t in tools if t.name == "exec")
        assert "cwd" in exec_tool.inputSchema.get("properties", {})
        assert "cwd" in exec_tool.inputSchema.get("required", [])

        result = await c.call_tool("exec", {"cmd": ["pwd"], "cwd": "/tmp", "timeout_ms": 10000})
        text = result.content[0].text if result.content else ""
        assert "/tmp" in text


async def test_cwd_always_set_to_description(make_cwd_server) -> None:
    """AlwaysSetTo: tool description mentions the fixed cwd."""
    server = make_cwd_server(AlwaysSetTo(value=Path("/var")))
    async with Client(server) as c:
        tools = await c.list_tools()
        exec_tool = next(t for t in tools if t.name == "exec")
        assert "/var" in (exec_tool.description or "")


if __name__ == "__main__":
    pytest_bazel.main()
