from __future__ import annotations

import pytest

from adgn.mcp._shared.types import ExecInput

# All tests below require structuredContent and call via the typed client


@pytest.mark.requires_docker
@pytest.mark.asyncio
async def test_hello_world(docker_exec_server_alpine, make_typed_mcp) -> None:
    async with make_typed_mcp(docker_exec_server_alpine, "docker") as (
        client,
        session,
    ):
        tools = await session.list_tools()
        names = {t.name for t in tools.tools}
        assert "docker_exec" in names

        res = await client.docker_exec(ExecInput(cmd=["/bin/echo", "hello"], timeout_ms=10_000))
        assert res.exit_code == 0
        assert res.timed_out is False
        assert "hello" in (res.stdout or "")


@pytest.mark.requires_docker
@pytest.mark.asyncio
async def test_stderr_and_exit_code(docker_exec_server_alpine, make_typed_mcp) -> None:
    async with make_typed_mcp(docker_exec_server_alpine, "docker") as (
        client,
        _session,
    ):
        res = await client.docker_exec(
            ExecInput(cmd=["sh", "-lc", "echo err 1>&2; exit 3"], timeout_ms=10_000)
        )
        expected_err_exit = 3
        assert res.exit_code == expected_err_exit
        assert "err" in (res.stderr or "")


@pytest.mark.requires_docker
@pytest.mark.asyncio
async def test_timeout_flag(docker_exec_server_alpine, make_typed_mcp) -> None:
    async with make_typed_mcp(docker_exec_server_alpine, "docker") as (
        client,
        _session,
    ):
        res = await client.docker_exec(ExecInput(cmd=["sh", "-lc", "sleep 5"], timeout_ms=500))
        assert res.timed_out is True
        assert res.exit_code in (None, 124, 143, 137, 1, 255)
