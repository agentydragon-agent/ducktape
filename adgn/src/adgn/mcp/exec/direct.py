from __future__ import annotations

from pathlib import Path

from fastmcp.exceptions import ToolError
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


def make_direct_exec_server(name: str = "exec", *, default_cwd: Path | None = None) -> EnhancedFastMCP:
    """FastMCP server exposing a direct (unsandboxed) exec tool.

    - Tool name: exec(cmd, max_bytes, cwd?, timeout_ms, stdin_text?)
    """
    mcp = EnhancedFastMCP(name, instructions="Local command execution (unsandboxed)")

    @mcp.flat_model()
    async def exec(input: DirectExecArgs) -> BaseExecResult:
        """Execute a command locally (no sandbox)."""
        if not input.cmd or not all(isinstance(x, str) for x in input.cmd):
            raise ToolError("INVALID_CMD: cmd must be a non-empty list[str]")
        cwd_val: Path | None = Path(input.cwd) if input.cwd else None
        if cwd_val is None and default_cwd is not None:
            cwd_val = default_cwd

        timeout_s = max(0.001, input.timeout_ms / 1000.0)
        outcome = await run_proc(input.cmd, timeout_s, cwd=cwd_val, stdin=input.stdin_text)
        return render_outcome_to_result(outcome, input.max_bytes)

    return mcp


async def attach_direct_exec(comp: Compositor, *, name: str = "exec", default_cwd: Path | None = None):
    """Attach a direct (unsandboxed) exec server in-proc."""
    server = make_direct_exec_server(name=name, default_cwd=default_cwd)
    await comp.mount_inproc(name, server)
    return server
