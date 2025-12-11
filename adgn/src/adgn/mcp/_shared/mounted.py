"""Mounted server wrapper bundling prefix and server instance."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Generic, TypeVar

from fastmcp import FastMCP

from adgn.mcp._shared.naming import build_mcp_function

if TYPE_CHECKING:
    from fastmcp.tools import FunctionTool


T = TypeVar("T", bound=FastMCP)


@dataclass
class Mounted(Generic[T]):
    """A mounted server with its mount prefix and instance.

    This bundles the mount prefix and server together, eliminating the need
    for separate mount prefix constants.

    Example:
        runtime: Mounted[RuntimeServer] = Mounted(
            prefix="runtime",
            server=RuntimeServer(...)
        )

        # Access prefix: runtime.prefix
        # Access server: runtime.server
        # Access tool: runtime.server.exec_tool.name

        # Build tool call requests via TypedBootstrapBuilder:
        builder = TypedBootstrapBuilder()
        call = builder.call_mounted(runtime, runtime.server.exec_tool, ExecInput(...))
    """

    prefix: str
    server: T

    def tool_name(self, tool: "FunctionTool") -> str:
        """Get fully-qualified MCP tool name.

        Args:
            tool: FunctionTool from self.server.some_tool

        Returns:
            Fully-qualified tool name (e.g., "lint_submit_submit_result")

        Example:
            submit_tool_name = comp.lint_submit.tool_name(comp.lint_submit.server.submit_result_tool)
        """
        return build_mcp_function(self.prefix, tool.name)
