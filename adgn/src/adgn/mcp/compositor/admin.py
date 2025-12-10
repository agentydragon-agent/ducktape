from typing import Literal

from fastmcp.mcp_config import MCPServerTypes, RemoteMCPServer, StdioMCPServer
from fastmcp.tools import FunctionTool
from pydantic import Field

from adgn.mcp._shared.types import SimpleOk
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.enhanced import EnhancedFastMCP
from adgn.openai_utils.pydantic_strict_mode import OpenAIStrictModeBaseModel


class KeyValue(OpenAIStrictModeBaseModel):
    """Key-value pair for env vars and headers."""

    key: str
    value: str


class StdioServerSpec(OpenAIStrictModeBaseModel):
    """Stdio server spec."""

    type: Literal["stdio"] = "stdio"
    command: str = Field(description="Command to execute")
    args: list[str] | None = Field(default=None, description="Command arguments")
    env: list[KeyValue] | None = Field(default=None, description="Environment variables")


class HttpServerSpec(OpenAIStrictModeBaseModel):
    """HTTP server spec."""

    type: Literal["http"] = "http"
    url: str = Field(description="HTTP server URL")
    headers: list[KeyValue] | None = Field(default=None, description="HTTP headers")


# Plain union (generates anyOf, not oneOf) - OpenAI strict mode compatible
ServerSpec = StdioServerSpec | HttpServerSpec


class AttachServerArgs(OpenAIStrictModeBaseModel):
    name: str = Field(description="Mount name (must be unique and not contain '__')")
    spec: ServerSpec = Field(description="Server spec (stdio or http)")


class DetachServerArgs(OpenAIStrictModeBaseModel):
    name: str


def convert_mcp_server_types_to_spec(mcp_spec: MCPServerTypes) -> ServerSpec:
    """Convert fastmcp's MCPServerTypes to our facade ServerSpec.

    This is the inverse of _convert_spec_to_mcp_server_types.
    Used when calling attach_server with specs from external sources.
    """
    if isinstance(mcp_spec, StdioMCPServer):
        env_list = [KeyValue(key=k, value=v) for k, v in mcp_spec.env.items()] if mcp_spec.env else None
        return StdioServerSpec(command=mcp_spec.command, args=mcp_spec.args if mcp_spec.args else None, env=env_list)
    if isinstance(mcp_spec, RemoteMCPServer):
        headers_list = [KeyValue(key=k, value=v) for k, v in mcp_spec.headers.items()] if mcp_spec.headers else None
        return HttpServerSpec(url=mcp_spec.url, headers=headers_list)
    raise TypeError(f"Unsupported MCP server type: {type(mcp_spec)}")


class CompositorAdminServer(EnhancedFastMCP):
    """Compositor admin MCP server with typed tool access.

    Provides admin tools for mounting/unmounting/listing servers.
    Subclasses EnhancedFastMCP and adds typed tool attributes.
    """

    # Tool references (assigned in __init__)
    attach_server_tool: FunctionTool
    detach_server_tool: FunctionTool

    def __init__(self, *, compositor: Compositor):
        """Create admin MCP server for mounting/unmounting/listing servers.

        Args:
            compositor: Compositor instance to manage

        Notes:
            - Attaches external transports only (stdio/http). In-proc mounts are wired by the host runtime.
            - All tool calls go through the Compositor and policy middleware (when mounted under it).
        """
        super().__init__(
            "Compositor Admin MCP Server",
            instructions=(
                "Compositor mount lifecycle admin (attach/detach/list). In-proc servers are managed by the runtime."
            ),
        )

        self._compositor = compositor

        def _convert_spec_to_mcp_server_types(spec: ServerSpec) -> MCPServerTypes:
            """Convert our facade types to fastmcp's MCPServerTypes."""
            if isinstance(spec, StdioServerSpec):
                env_dict = {kv.key: kv.value for kv in spec.env} if spec.env is not None else {}
                args_list = spec.args if spec.args is not None else []
                return StdioMCPServer(command=spec.command, args=args_list, env=env_dict)
            # HttpServerSpec
            headers_dict = {kv.key: kv.value for kv in spec.headers} if spec.headers is not None else {}
            return RemoteMCPServer(url=spec.url, headers=headers_dict)

        # Register tools using clean pattern
        async def attach_server(input: AttachServerArgs) -> SimpleOk:
            """Attach an MCP server (stdio or http transport)."""
            mcp_spec = _convert_spec_to_mcp_server_types(input.spec)
            await self._compositor.mount_server(input.name, mcp_spec)
            return SimpleOk(ok=True)

        self.attach_server_tool = self.flat_model()(attach_server)

        async def detach_server(input: DetachServerArgs) -> SimpleOk:
            """Detach a mounted MCP server."""
            await self._compositor.unmount_server(input.name)
            return SimpleOk(ok=True)

        self.detach_server_tool = self.flat_model()(detach_server)
