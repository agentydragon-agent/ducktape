"""
FastMCP server: per-session Docker container exec.

- One container per FastMCP session (created in lifespan; stopped on exit)
- Network mode configurable (default: none); RO/RW volumes as provided; working_dir is writable
- Single source of truth for container contents: host-side docker image history (CreatedBy)
"""

from __future__ import annotations

from adgn.mcp._shared.container_session import ContainerOptions, make_container_lifespan, register_container
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP


def make_container_exec_server(
    opts: ContainerOptions, *, name: str = "docker", tool_exec_name: str = "exec"
) -> NotifyingFastMCP:
    """Create a generic per-session container exec FastMCP server.

    Callers must pass a fully constructed ContainerOptions (no kwargs).
    """
    server = NotifyingFastMCP(
        name,
        instructions="Per-session container exec. See resource container.info for details.",
        lifespan=make_container_lifespan(opts),
    )
    register_container(server, opts, tool_name=tool_exec_name)
    return server


async def attach_container_exec(
    comp, opts: ContainerOptions, *, server_name: str = "docker", tool_exec_name: str = "exec"
):
    """Attach a per-session container exec server (no auth, in-proc)."""
    server = make_container_exec_server(opts, name=server_name, tool_exec_name=tool_exec_name)
    # Compositor mount path (preferred)
    await comp.mount_inproc(server_name, server)
