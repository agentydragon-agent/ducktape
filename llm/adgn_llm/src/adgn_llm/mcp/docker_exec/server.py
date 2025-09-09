#!/usr/bin/env python3
"""
FastMCP server: per-session Docker container exec.

- One container per FastMCP session (created in lifespan; stopped on exit)
- Network mode configurable (default: none); RO/RW volumes as provided; working_dir is writable
- Single source of truth for container contents: host-side docker image history (CreatedBy)
- Tool:
  - exec(cmd, cwd?, env?, user?, tty?, shell?, timeout_secs?) -> {exit_code, timed_out, stdout, stderr}

Use make_container_exec_mcp(...) to construct a server instance.
"""

from __future__ import annotations

from typing import Dict

from mcp.server.fastmcp import FastMCP

# Shared names for wiring and renderers
SERVER_NAME = "docker"
TOOL_EXEC_NAME = "docker_exec"

# Shared container session core
from .._shared.container_session import (
    make_container_lifespan,
    register_container,
    NetworkMode,
)


def make_container_exec_mcp(
    *,
    image: str,
    working_dir: str = "/workspace",
    volumes: Dict[str, Dict[str, str]] | list[str] | None = None,
    network_mode: NetworkMode = NetworkMode.NONE,
    describe: bool = True,
    environment: Dict[str, str] | None = None,
    labels: Dict[str, str] | None = None,
) -> FastMCP:
    """Create a generic per-session container exec FastMCP server.

    Args:
      image: Docker image to use for the session container
      working_dir: writable directory in the container
      volumes: Docker volumes spec (dict or list); use dict to set bind/mode
      describe: whether to populate a human-readable description (docker history)
    """
    lifespan = make_container_lifespan(
        image=image,
        working_dir=working_dir,
        volumes=volumes,
        network_mode=network_mode,
        describe=describe,
        environment=environment,
        labels=labels,
    )
    server = FastMCP(
        "container_exec",
        instructions="Per-session container exec. See resource container.info for details.",
        lifespan=lifespan,
    )
    register_container(server, tool_name=TOOL_EXEC_NAME)
    return server
