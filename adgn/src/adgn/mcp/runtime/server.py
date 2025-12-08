from __future__ import annotations

from adgn.mcp._shared.constants import RUNTIME_EXEC_TOOL_NAME, RUNTIME_SERVER_NAME
from adgn.mcp._shared.container_session import ContainerOptions
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.enhanced import EnhancedFastMCP
from adgn.mcp.exec.docker.server import make_container_exec_server


def make_runtime_server(opts: ContainerOptions) -> EnhancedFastMCP:
    """Create the runtime server (container exec with enforced adgn mount).

    This wraps docker_exec to expose a simple container exec tool. No host mounts
    are enforced by default.
    """
    return make_container_exec_server(opts, name="Runtime", tool_exec_name=RUNTIME_EXEC_TOOL_NAME)


async def attach_runtime(comp: Compositor, opts: ContainerOptions) -> None:
    """Attach the runtime server (enforced adgn mount) in-proc with bearer auth."""
    server = make_container_exec_server(opts, name=RUNTIME_SERVER_NAME, tool_exec_name=RUNTIME_EXEC_TOOL_NAME)
    # Compositor mount path (preferred)
    await comp.mount_inproc(RUNTIME_SERVER_NAME, server)
