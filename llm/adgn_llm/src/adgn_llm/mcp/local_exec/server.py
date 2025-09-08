from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from adgn_llm.mini_codex.local_tools import exec_handler


def make_local_exec_mcp(
    name: str = "local",
    *,
    default_cwd: str | None = None,
    sandbox_enabled: bool = True,
) -> FastMCP:
    """FastMCP server exposing a local exec tool.

    Tools:
      - exec(cmd: list[str], cwd: str | None = None, timeout_ms: int | None = None)
        → {exit:int, stdout:str, stderr:str}
    """
    mcp = FastMCP(name, instructions="Local command execution")

    @mcp.tool()
    def exec(cmd: list[str], cwd: str | None = None, timeout_ms: int | None = None) -> dict[str, Any]:  # noqa: A003
        return exec_handler(
            {"cmd": cmd, "cwd": cwd or default_cwd, "timeout_ms": timeout_ms},
            sandbox_enabled=sandbox_enabled,
        )

    return mcp
