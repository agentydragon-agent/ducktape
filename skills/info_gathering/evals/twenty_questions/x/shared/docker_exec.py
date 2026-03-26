"""Scratch container exec MCP server for agent computation.

Wraps mcp_infra's ContainerExecServer — a full MCP server providing an `exec` tool
with proper stream handling, timeouts, and output formatting. The server is yielded
so each framework can consume it in its native way (e.g., PydanticAI's FastMCPToolset,
or via fastmcp.Client for others).
"""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import aiodocker

from mcp_infra.exec.docker.container_session import AlwaysSetTo, ContainerOptions
from mcp_infra.exec.docker.server import ContainerExecServer

logger = logging.getLogger(__name__)


@asynccontextmanager
async def scratch_exec_server(image: str = "alpine:latest") -> AsyncGenerator[ContainerExecServer]:
    """Create a scratch container with an MCP exec tool server.

    The server exposes an `exec` tool with cmd (list[str]) and timeout_ms (int).
    cwd is fixed to /tmp (hidden from the model). User and env fields are disabled.
    """
    opts = ContainerOptions(image=image)
    async with aiodocker.Docker() as docker_client:
        server = ContainerExecServer(
            docker_client,
            opts,
            allow_user_field=False,
            allow_env_field=False,
            cwd_policy=AlwaysSetTo(value=Path("/tmp")),
        )
        logger.info("Scratch exec server created (image=%s)", image)
        yield server
