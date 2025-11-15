"""Typed stubs for chat MCP servers."""

from adgn.mcp.chat.server import PostInput, PostResult, ReadPendingInput, ReadPendingResult
from adgn.mcp.testing.server_stubs import ServerStub


class ChatServerStub(ServerStub):
    """Typed stub for chat server operations."""

    async def post(self, input: PostInput) -> PostResult: ...
    async def read_pending_messages(self, input: ReadPendingInput) -> ReadPendingResult: ...
