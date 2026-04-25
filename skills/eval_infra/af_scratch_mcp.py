"""Hand a Microsoft Agent Framework `Agent` an `exec` MCP tool that runs in a
scratch Docker container.

`scratch_exec_mcp_tool` builds an `MCPStdioTool` that launches the
`mcp_infra.exec.docker.launcher` CLI as a subprocess. The launcher boots a
`ContainerExecServer` (configured the same way `scratch_exec_server` does:
host network, proxy env, locked-down user/env/cwd) and speaks MCP over
stdio. AF then drives tool dispatch natively — no FastMCP client, no
hand-rolled FunctionTool bridge.

Usage:

    async with scratch_exec_mcp_tool(binds=[...], working_dir=Path("/work")) as exec_tool:
        agent = Agent(client=..., tools=[exec_tool, ...])
        await agent.run(...)
"""

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from agent_framework import MCPStdioTool

from mcp_infra.exec.docker.types import AlwaysSetTo, BindMount, ContainerExecServerConfig
from util.bazel.runfiles import get_required_path

_LAUNCHER_RLOCATION = "_main/mcp_infra/exec/docker_launcher"


def _proxy_env() -> dict[str, str]:
    """Collect HTTP(S) proxy env vars for container networking."""
    env: dict[str, str] = {}
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "NO_PROXY", "no_proxy"):
        if val := os.environ.get(var):
            env[var] = val
    return env


@asynccontextmanager
async def scratch_exec_mcp_tool(
    name: str = "exec",
    *,
    image: str = "python:3.13-slim",
    binds: list[BindMount] | None = None,
    working_dir: Path = Path("/tmp"),
) -> AsyncGenerator[MCPStdioTool]:
    """Yield an `MCPStdioTool` that exposes a scratch container's `exec` tool.

    The container has host networking, proxy env wired, and `cwd`/`user`/`env`
    fields hidden from the model. `binds` are mounted into the container at
    creation; `working_dir` becomes the container cwd.
    """
    config = ContainerExecServerConfig(
        image=image,
        working_dir=working_dir,
        network_mode="host",
        environment=_proxy_env(),
        allow_user_field=False,
        allow_env_field=False,
        cwd_policy=AlwaysSetTo(value=working_dir),
        binds=list(binds or []),
    )
    launcher = get_required_path(_LAUNCHER_RLOCATION)
    async with MCPStdioTool(name=name, command=str(launcher), args=["--config", config.model_dump_json()]) as tool:
        yield tool
