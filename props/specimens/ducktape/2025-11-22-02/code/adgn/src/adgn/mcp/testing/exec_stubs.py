"""Typed stubs for exec MCP servers."""

from adgn.mcp.exec.bwrap import BwrapExecArgs
from adgn.mcp.exec.direct import DirectExecArgs
from adgn.mcp.exec.models import BaseExecResult
from adgn.mcp.exec.seatbelt import SandboxExecArgs, SandboxExecResult
from adgn.mcp.stubs.server_stubs import ServerStub


class DirectExecServerStub(ServerStub):
    """Typed stub for direct (unsandboxed) exec server operations."""

    async def exec(self, input: DirectExecArgs) -> BaseExecResult:
        raise NotImplementedError  # Auto-wired at runtime


class BwrapExecServerStub(ServerStub):
    """Typed stub for bubblewrap sandboxed exec server operations."""

    async def exec(self, input: BwrapExecArgs) -> BaseExecResult:
        raise NotImplementedError  # Auto-wired at runtime


class SeatbeltExecServerStub(ServerStub):
    """Typed stub for seatbelt sandboxed exec server operations."""

    async def sandbox_exec(self, input: SandboxExecArgs) -> SandboxExecResult:
        raise NotImplementedError  # Auto-wired at runtime
