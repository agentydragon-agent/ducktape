from __future__ import annotations

from adgn.mcp._shared.constants import RUNTIME_EXEC_TOOL_NAME, RUNTIME_SERVER_NAME
from adgn.mcp._shared.container_session import ContainerOptions
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.exec.docker.server import attach_container_exec, make_container_exec_server
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP


def make_runtime_server(opts: ContainerOptions) -> NotifyingFastMCP:
    """Create the runtime server (container exec with enforced adgn mount).

    This wraps docker_exec to expose a simple container exec tool. No host mounts
    are enforced by default.
    """
    return make_container_exec_server(opts, name="Runtime", tool_exec_name=RUNTIME_EXEC_TOOL_NAME)


async def attach_runtime(comp: Compositor, opts: ContainerOptions) -> None:
    """Attach the runtime server (enforced adgn mount) in-proc with bearer auth."""
    # Reuse docker_exec attach with Compositor
    await attach_container_exec(comp, opts, server_name=RUNTIME_SERVER_NAME, tool_exec_name=RUNTIME_EXEC_TOOL_NAME)
