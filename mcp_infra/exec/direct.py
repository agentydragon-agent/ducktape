from __future__ import annotations

from pathlib import Path

import mcp.types as mcp_types
from fastmcp.exceptions import ToolError

from mcp_infra.enhanced.flat_mixin import FlatTool
from mcp_infra.enhanced.server import EnhancedFastMCP
from mcp_infra.exec.models import BaseExecResult
from mcp_infra.exec.read_image import ReadImageInput, validate_and_encode_image
from mcp_infra.exec.subprocess_exec import SubprocessExecArgs, run_exec


class DirectExecServer(EnhancedFastMCP):
    """Direct (unsandboxed) exec MCP server with typed tool access."""

    exec_tool: FlatTool

    def __init__(self, *, default_cwd: Path | None = None):
        super().__init__("Direct Exec MCP Server", instructions="Local command execution (unsandboxed)")

        default_cwd_val = default_cwd

        async def exec(input: SubprocessExecArgs) -> BaseExecResult:
            """Execute a command locally (no sandbox)."""
            try:
                return await run_exec(input, default_cwd=default_cwd_val)
            except ValueError as e:
                raise ToolError(str(e)) from e

        self.exec_tool = self.flat_model()(exec)

        def read_image(input: ReadImageInput) -> list[mcp_types.ImageContent]:
            """Read an image file and return it for the model to see."""
            p = Path(input.path)
            if not p.is_file():
                raise ValueError(f"Not a file: {input.path}")
            return [validate_and_encode_image(p.read_bytes(), input.path)]

        self.read_image_tool = self.flat_model()(read_image)
