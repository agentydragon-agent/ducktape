from __future__ import annotations

from pathlib import Path

from fastmcp.exceptions import ToolError
from fastmcp.tools import FunctionTool
from pydantic import BaseModel, ConfigDict, Field

from adgn.mcp.compositor.server import Compositor
from adgn.mcp.enhanced import EnhancedFastMCP
from adgn.mcp.exec.models import BaseExecResult, TimeoutMs, render_outcome_to_result
from adgn.mcp.exec.subprocess import run_proc


class DirectExecArgs(BaseModel):
    cmd: list[str]
    max_bytes: int = Field(..., ge=0, le=100_000, description="Applies to stdin and captures")
    # str not Path: OpenAI strict mode doesn't accept format="path" in JSON schemas
    cwd: str | None = None
    timeout_ms: TimeoutMs
    stdin_text: str | None = None

    model_config = ConfigDict(extra="forbid")


class DirectExecServer(EnhancedFastMCP):
    """Direct (unsandboxed) exec MCP server with typed tool access."""

    # Tool references (assigned in __init__)
    exec_tool: FunctionTool

    def __init__(self, *, default_cwd: Path | None = None):
        """Create a direct (unsandboxed) exec MCP server.

        Args:
            default_cwd: Default working directory for commands when not specified
        """
        super().__init__("Direct Exec MCP Server", instructions="Local command execution (unsandboxed)")

        # Capture default_cwd in closure
        default_cwd_val = default_cwd

        async def exec(input: DirectExecArgs) -> BaseExecResult:
            """Execute a command locally (no sandbox)."""
            if not input.cmd or not all(isinstance(x, str) for x in input.cmd):
                raise ToolError("INVALID_CMD: cmd must be a non-empty list[str]")
            cwd_val: Path | None = Path(input.cwd) if input.cwd else None
            if cwd_val is None and default_cwd_val is not None:
                cwd_val = default_cwd_val

            timeout_s = max(0.001, input.timeout_ms / 1000.0)
            outcome = await run_proc(input.cmd, timeout_s, cwd=cwd_val, stdin=input.stdin_text)
            return render_outcome_to_result(outcome, input.max_bytes)

        self.exec_tool = self.flat_model()(exec)


async def attach_direct_exec(comp: Compositor, *, name: str = "exec", default_cwd: Path | None = None):
    """Attach a direct (unsandboxed) exec server in-proc."""
    server = DirectExecServer(default_cwd=default_cwd)
    await comp.mount_inproc(name, server)
    return server
