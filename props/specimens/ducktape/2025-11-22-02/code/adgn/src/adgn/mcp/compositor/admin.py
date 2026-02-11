from fastmcp.mcp_config import MCPServerTypes
from pydantic import BaseModel, ConfigDict, Field

from adgn.mcp._shared.constants import COMPOSITOR_ADMIN_SERVER_NAME
from adgn.mcp._shared.types import SimpleOk
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP


class AttachServerArgs(BaseModel):
    name: str = Field(description="Mount name (must be unique and not contain '__')")
    spec: MCPServerTypes = Field(description="Typed MCP server spec (stdio/http/transforming)")
    model_config = ConfigDict(extra="forbid")


class DetachServerArgs(BaseModel):
    name: str
    model_config = ConfigDict(extra="forbid")


def make_compositor_admin_server(
    *, compositor: Compositor, name: str = COMPOSITOR_ADMIN_SERVER_NAME
) -> NotifyingFastMCP:
    """Create an admin MCP server for mounting/unmounting/listing servers.

    Notes
    - Attaches external transports only (stdio/http). In-proc mounts are wired by the host runtime.
    - All tool calls go through the Compositor and policy middleware (when mounted under it).
    """
    mcp = NotifyingFastMCP(
        name,
        instructions=(
            "Compositor mount lifecycle admin (attach/detach/list). In-proc servers are managed by the runtime."
        ),
    )

    @mcp.flat_model()
    async def attach_server(input: AttachServerArgs) -> SimpleOk:
        await compositor.mount_server(input.name, input.spec)
        return SimpleOk(ok=True)

    @mcp.flat_model()
    async def detach_server(input: DetachServerArgs) -> SimpleOk:
        await compositor.unmount_server(input.name)
        return SimpleOk(ok=True)

    return mcp
