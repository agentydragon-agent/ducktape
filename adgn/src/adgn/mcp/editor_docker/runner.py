from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import aiodocker

from adgn.mcp.editor_docker.submit_server import EditorSubmitServer
from adgn.mcp.http_gateway import MCPHttpGateway, mcp_http_gateway
from mcp_infra.compositor.server import Compositor
from mcp_infra.constants import WORKING_DIR
from mcp_infra.container_session import ContainerOptions
from mcp_infra.exec.docker.server import ContainerExecServer
from mcp_infra.mounted import Mounted
from mcp_infra.resources.server import ResourcesServer

if TYPE_CHECKING:
    from fastmcp.server.auth import AuthProvider

DEFAULT_NETWORK = "bridge"


@dataclass
class EditorDockerSession:
    submit_server: EditorSubmitServer
    gateway: MCPHttpGateway
    container_server: ContainerExecServer
    compositor: Compositor
    runtime: Mounted[ContainerExecServer]
    resources: Mounted[ResourcesServer]
    filename: str
    original_content: str | None = None

    async def shutdown(self) -> None:
        await self.gateway.shutdown()
        await Compositor.__aexit__(self.compositor, None, None, None)


def writeback_success(host_file: Path, content: str) -> None:
    """Write submitted content verbatim to the host file."""
    host_file.write_text(content, encoding="utf-8")


@asynccontextmanager
async def editor_docker_session(
    *, file_path: Path, docker_client: aiodocker.Docker, image_id: str, network_name: str = DEFAULT_NETWORK
) -> AsyncIterator[EditorDockerSession]:
    """Create a docker-exec + submit-server session for a single file.

    - Reads file content into memory (not mounted).
    - Starts submit MCP server reachable from the container via bridge gateway.
    - Container runs the editor agent image (with /init baked in).
    """
    original_content = file_path.read_text(encoding="utf-8")
    filename = file_path.name

    def _make_server(auth: AuthProvider) -> EditorSubmitServer:
        return EditorSubmitServer(original_content=original_content, filename=filename)

    # Submit server exposed over HTTP for helper; compositor stays local for runtime/resources
    async with mcp_http_gateway(
        make_server=_make_server, docker_client=docker_client, network_name=network_name
    ) as gateway:
        env = {"MCP_SERVER_URL": gateway.url_for_container, "MCP_SERVER_TOKEN": gateway.token}

        opts = ContainerOptions(
            image=image_id, working_dir=WORKING_DIR, binds=[], network_mode=network_name, environment=env
        )

        compositor = Compositor()
        await Compositor.__aenter__(compositor)
        resources_mount = compositor.resources

        container_server = ContainerExecServer(docker_client, opts)
        runtime_mount = await compositor.mount_inproc(
            ContainerExecServer.DOCKER_MOUNT_PREFIX, container_server, pinned=True
        )

        session = EditorDockerSession(
            submit_server=gateway.server,  # type: ignore[arg-type]
            gateway=gateway,
            container_server=container_server,
            compositor=compositor,
            runtime=runtime_mount,
            resources=resources_mount,
            original_content=original_content,
            filename=filename,
        )
        try:
            yield session
        finally:
            await session.shutdown()
