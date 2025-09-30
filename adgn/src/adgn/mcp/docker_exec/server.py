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

from adgn.mcp._shared.fastmcp_helpers import SafeFastMCP

from .._shared.container_session import (
    ContainerOptions,
    make_container_lifespan,
    register_container,
)

# Shared names for wiring and renderers
SERVER_NAME = "docker"
TOOL_EXEC_NAME = "docker_exec"


def make_container_exec_mcp(opts: ContainerOptions) -> SafeFastMCP:
    """Create a generic per-session container exec FastMCP server.

    Callers must pass a fully constructed ContainerOptions (no kwargs).
    """
    lifespan = make_container_lifespan(opts)
    server = SafeFastMCP(
        SERVER_NAME,
        instructions="Per-session container exec. See resource container.info for details.",
        lifespan=lifespan,
    )
    register_container(server, tool_name=TOOL_EXEC_NAME)
    return server
