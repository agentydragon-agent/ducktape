import asyncio
import shutil

import pytest
from fastmcp.client import Client
from fastmcp.mcp_config import StdioMCPServer

from mcp_infra.exec.direct import DirectExecArgs, DirectExecServer
from mcp_infra.exec.docker.server import ContainerExecServer
from mcp_infra.exec.models import BaseExecResult, Exited
from mcp_infra.naming import build_mcp_function
from mcp_infra.prefix import MCPMountPrefix
from mcp_infra.stubs.typed_stubs import ToolStub

# FastMCP stdio client (hard import)


async def test_stdio_server_list_tools(compositor, compositor_client) -> None:
    """Smoke test: connect to server-everything (stdio) and list tools.

    Skips if npx or FastMCP stdio client are unavailable.
    """
    if shutil.which("npx") is None:
        pytest.skip("npx not found in PATH; required for server-everything")

    # Preflight: verify server-everything can start (help) quickly; skip if not
    try:
        proc = await asyncio.create_subprocess_exec(
            "npx",
            "--yes",
            "@modelcontextprotocol/server-everything",
            "stdio",
            "--help",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.wait(), timeout=20)
    except Exception as e:  # pragma: no cover - infra-dependent
        pytest.skip(f"preflight failed: {e}")
    if proc.returncode != 0:
        pytest.skip(f"server-everything stdio help failed (rc={proc.returncode})")

    spec = StdioMCPServer(command="npx", args=["@modelcontextprotocol/server-everything", "stdio"])

    # Mount the stdio server
    await compositor.mount_server("everything", spec)

    tools = await compositor_client.list_tools()
    assert isinstance(tools, list)
    assert any(t.name.startswith("everything_") for t in tools)


async def test_direct_inprocess_server(compositor, compositor_client) -> None:
    """Direct (unsandboxed) in-process FastMCP exec tool mounted in a Compositor."""

    srv = DirectExecServer()
    await compositor.mount_inproc(MCPMountPrefix("local"), srv)

    tools = await compositor_client.list_tools()
    # Tools are composed under the compositor with namespaced tool names
    tool_name = build_mcp_function(MCPMountPrefix("local"), "exec")
    assert any(t.name == tool_name for t in tools)
    # Sanity-call exec via the namespaced tool using the typed helper
    exec_stub = ToolStub(compositor_client, tool_name, BaseExecResult)
    result = await exec_stub(DirectExecArgs(cmd=["/bin/echo", "hello"], max_bytes=100_000, timeout_ms=5000))
    # Compare whole exit object
    assert result.exit == Exited(exit_code=0)


@pytest.mark.requires_docker
async def test_inproc_container_exec_exposes_container_info_resource(
    docker_exec_server_py312slim: ContainerExecServer,
) -> None:
    """in-proc container exec exposes a container.info resource."""

    # Call the server directly to read the resource; no manager needed here
    async with Client(docker_exec_server_py312slim) as sess:
        res = await sess.read_resource_mcp(docker_exec_server_py312slim.container_info_resource.uri)
        assert res.contents, "container.info returned no contents"
