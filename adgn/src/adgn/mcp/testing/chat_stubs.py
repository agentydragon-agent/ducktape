"""Typed stubs for chat MCP servers."""

from adgn.mcp.chat.server import PostInput, PostResult, ReadPendingInput, ReadPendingResult
from adgn.mcp.stubs.server_stubs import ServerStub


class ChatServerStub(ServerStub):
    """Typed stub for chat server operations."""

    async def post(self, input: PostInput) -> PostResult:
        raise NotImplementedError  # Auto-wired at runtime

    async def read_pending_messages(self, input: ReadPendingInput) -> ReadPendingResult:
        raise NotImplementedError  # Auto-wired at runtime
