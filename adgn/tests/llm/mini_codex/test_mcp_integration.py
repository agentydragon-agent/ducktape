import asyncio
import shutil

import pytest

from adgn.llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn.llm.mcp.local_exec.server import make_local_exec_mcp
from adgn.llm.mcp.testing.typed_stubs import TypedClient
from adgn.llm.mcp.exec_common.models import StreamOut
from adgn.llm.mini_codex.mcp_manager import McpManager

# FastMCP stdio client (hard import)


@pytest.mark.asyncio
async def test_stdio_server_list_tools() -> None:
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

    spec = McpManager.slot_from_spec(
        "everything",
        {
            "transport": "stdio",
            "command": "npx",
            "args": ["@modelcontextprotocol/server-everything", "stdio"],
        },
    )

    async with McpManager({"everything": spec}) as mcp:
        specs = await mcp.list_tools()
        assert isinstance(specs, list)
        assert any(s.get("type") == "function" for s in specs)
        # At least one tool is namespaced under everything
        assert any((s.get("name") or "").startswith("mcp__everything__") for s in specs)


@pytest.mark.asyncio
async def test_local_inprocess_server() -> None:
    """Local in-process FastMCP exec tool via memory streams (no stdio)."""

    # Import FastMCP in-proc helpers locally to avoid global import churn

    srv = make_local_exec_mcp(
        "local", sandbox_enabled=False
    )  # run unsandboxed for portability in CI/macOS
    spec = make_inproc_slot_spec(srv)
    async with McpManager({"local": spec}) as mcp:
        specs = await mcp.list_tools()
        names = [s.get("name") for s in specs]
        assert "mcp__local__exec" in names

        # Typed client sanity call
        session = await mcp.get_session("local")
        client = TypedClient.from_server(srv, session)
        Args = client.models["exec"].Input
        res = await client.exec(
            Args(cmd=["/bin/echo", "hello"], max_bytes=100000, timeout_ms=5000)
        )
        assert res.exit == 0
        out = (
            res.stdout.text if isinstance(res.stdout, StreamOut) else (res.stdout or "")
        )
        assert "hello" in out


@pytest.mark.asyncio
@pytest.mark.requires_docker
async def test_inproc_container_exec_exposes_container_info_resource(
    docker_inproc_spec_py312: object,
) -> None:
    """in-proc container exec exposes a container.info resource."""

    async with McpManager({"docker": docker_inproc_spec_py312}) as mcp:
        res = await mcp.read_resource("docker", "resource://container.info")
        assert res.contents, "container.info returned no contents"
