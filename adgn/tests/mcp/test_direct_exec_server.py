from __future__ import annotations

from fastmcp.client import Client
import pytest

from adgn.mcp.direct_exec.server import DirectExecArgs, DirectExecResult, make_direct_exec_server
from adgn.mcp.testing.typed_stubs import TypedClient


@pytest.mark.asyncio
async def test_direct_exec_echo_inproc() -> None:
    """Direct exec (unsandboxed) in-proc server echo test."""

    server = make_direct_exec_server("exec")
    async with Client(server) as session:
        client = TypedClient.from_server(server, session)
        res: DirectExecResult = await client.exec(
            DirectExecArgs(cmd=["/bin/echo", "hello"], max_bytes=100000, timeout_ms=5000)
        )
        assert res.exit == 0
        assert res.stdout == "hello\n"
