from __future__ import annotations

import pytest

from adgn.mcp._shared.container_session import ContainerOptions
from adgn.mcp.docker_exec.server import make_container_exec_server


def _make_server(ephemeral: bool):
    opts = ContainerOptions(image="alpine:3.19", ephemeral=ephemeral)

    return make_container_exec_server(opts)


@pytest.mark.asyncio
@pytest.mark.requires_docker
async def test_ephemeral_exec_stdout_stderr_timeout(make_typed_mcp) -> None:
    server = _make_server(ephemeral=True)
    from adgn.mcp._shared.constants import EXIT_CODE_SIGTERM

    async with make_typed_mcp(server, "docker") as (client, _session):
        from adgn.mcp._shared.types import ExecInput

        # stdout
        r1 = await client.exec(ExecInput(cmd=["/bin/echo", "hello"], timeout_ms=5000))
        assert r1.exit_code == 0 and r1.timed_out is False and (r1.stdout or "").strip() == "hello"
        # stderr and nonzero exit
        r2 = await client.exec(
            ExecInput(cmd=["sh", "-lc", "echo err 1>&2; exit 3"], timeout_ms=5000)
        )
        assert r2.exit_code == 3 and "err" in (r2.stderr or "")
        # timeout
        r3 = await client.exec(ExecInput(cmd=["sh", "-lc", "sleep 5"], timeout_ms=500))
        assert r3.timed_out is True and r3.exit_code == EXIT_CODE_SIGTERM


@pytest.mark.asyncio
@pytest.mark.requires_docker
async def test_persession_exec_timeout_then_next_ok(make_typed_mcp) -> None:
    server = _make_server(ephemeral=False)
    from adgn.mcp._shared.constants import EXIT_CODE_SIGTERM

    async with make_typed_mcp(server, "docker") as (client, _session):
        from adgn.mcp._shared.types import ExecInput

        # Force timeout
        t1 = await client.exec(ExecInput(cmd=["sh", "-lc", "sleep 3"], timeout_ms=500))
        assert t1.timed_out is True and t1.exit_code == EXIT_CODE_SIGTERM
        # Next call should succeed after restart
        r1 = await client.exec(ExecInput(cmd=["/bin/echo", "ok"], timeout_ms=5000))
        assert r1.exit_code == 0 and (r1.stdout or "").strip() == "ok"
