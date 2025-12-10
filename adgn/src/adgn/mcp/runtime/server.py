from __future__ import annotations

import aiodocker

from adgn.mcp._shared.constants import RUNTIME_MOUNT_PREFIX
from adgn.mcp._shared.container_session import ContainerOptions
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.exec.docker.server import ContainerExecServer


class RuntimeServer(ContainerExecServer):
    """Runtime server (container exec) with typed tool access.

    This is a thin wrapper around ContainerExecServer for semantic clarity.
    """


async def attach_runtime(comp: Compositor, opts: ContainerOptions, docker_client: aiodocker.Docker) -> RuntimeServer:
    """Attach the runtime server (enforced adgn mount) in-proc with bearer auth.

    Args:
        comp: Compositor instance
        opts: Container configuration options
        docker_client: Async Docker client (managed by caller)

    Returns:
        RuntimeServer: The mounted server instance
    """
    server = RuntimeServer(opts, docker_client)
    # Compositor mount path (preferred)
    await comp.mount_inproc(RUNTIME_MOUNT_PREFIX, server)
    return server
