"""
FastMCP server: per-session Docker container exec.

- One container per FastMCP session (created in lifespan; stopped on exit)
- Network mode configurable (default: none); RO/RW volumes as provided; working_dir is writable
- Single source of truth for container contents: host-side docker image history (CreatedBy)
"""

from __future__ import annotations

from adgn.mcp._shared.constants import RUNTIME_CONTAINER_INFO_URI
from adgn.mcp._shared.container_session import ContainerOptions, make_container_lifespan, register_container
from adgn.mcp.enhanced import EnhancedFastMCP


def make_container_exec_server(
    opts: ContainerOptions, *, name: str = "docker", tool_exec_name: str = "exec"
) -> EnhancedFastMCP:
    """Create a generic per-session container exec FastMCP server."""
    server = EnhancedFastMCP(
        name,
        instructions=(
            f"Provides access to a Docker container.\n\n"
            f"Image history is available by reading the resource {RUNTIME_CONTAINER_INFO_URI}.\n\n"
            f"/tmp is writable and can be used as a scratchpad for notes, intermediate results, "
            f"or organizing your thoughts."
        ),
        lifespan=make_container_lifespan(opts),
    )
    register_container(server, opts, tool_name=tool_exec_name)
    return server
