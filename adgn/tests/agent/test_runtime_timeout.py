from __future__ import annotations

import pytest

from adgn.mcp._shared.naming import build_mcp_function
from adgn.mcp.exec.docker.server import ContainerExecServer
from adgn.mcp.exec.models import BaseExecResult, Exited, TimedOut, make_exec_input
from adgn.mcp.stubs.typed_stubs import ToolStub
from tests.conftest import make_container_opts


def _runtime_spec_persession(docker_client, image: str = "alpine:3.19"):
    return ContainerExecServer(
        make_container_opts(image, ephemeral=False),  # per-session container
        docker_client,
    )


@pytest.mark.requires_docker
async def test_runtime_per_session_timeout_then_next_call_ok(make_pg_client, async_docker_client) -> None:
    async with make_pg_client({"runtime": _runtime_spec_persession(async_docker_client)}) as mcp_client:
        # Cause a host-side timeout: sleep longer than timeout_ms
        # Namespaced exec via Compositor
        stub = ToolStub(mcp_client, build_mcp_function("runtime", "exec"), BaseExecResult)

        res_timeout = await stub(make_exec_input(["sh", "-lc", "sleep 3"], timeout_ms=500))
        assert isinstance(res_timeout.exit, TimedOut)

        # Next call should work; container should have been restarted
        res_ok = await stub(make_exec_input(["/bin/echo", "-n", "ok"], timeout_ms=5000))
        assert isinstance(res_ok.exit, Exited)
        assert res_ok.exit.exit_code == 0
        assert (res_ok.stdout or "") == "ok"
