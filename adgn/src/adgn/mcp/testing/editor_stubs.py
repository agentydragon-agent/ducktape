"""Typed stubs for editor MCP server."""

from adgn.mcp.editor_server import (
    AddLineAfterArgs,
    AddLineAfterResult,
    DeleteLineArgs,
    DeleteLineResult,
    DoneInput,
    DoneResponse,
    ReadInfoArgs,
    ReadInfoResult,
    ReadLineRangeArgs,
    ReadLineRangeResult,
    ReplaceTextAllArgs,
    ReplaceTextAllResult,
    ReplaceTextArgs,
    ReplaceTextResult,
    SaveArgs,
    SaveResult,
)
from adgn.mcp.stubs.server_stubs import ServerStub


class EditorServerStub(ServerStub):
    """Typed stub for editor server operations."""

    async def read_info(self, input: ReadInfoArgs) -> ReadInfoResult:
        raise NotImplementedError  # Auto-wired at runtime

    async def read_line_range(self, input: ReadLineRangeArgs) -> ReadLineRangeResult:
        raise NotImplementedError  # Auto-wired at runtime

    async def replace_text(self, input: ReplaceTextArgs) -> ReplaceTextResult:
        raise NotImplementedError  # Auto-wired at runtime

    async def replace_text_all(self, input: ReplaceTextAllArgs) -> ReplaceTextAllResult:
        raise NotImplementedError  # Auto-wired at runtime

    async def delete_line(self, input: DeleteLineArgs) -> DeleteLineResult:
        raise NotImplementedError  # Auto-wired at runtime

    async def add_line_after(self, input: AddLineAfterArgs) -> AddLineAfterResult:
        raise NotImplementedError  # Auto-wired at runtime

    async def save(self, input: SaveArgs) -> SaveResult:
        raise NotImplementedError  # Auto-wired at runtime

    async def done(self, input: DoneInput) -> DoneResponse:
        raise NotImplementedError  # Auto-wired at runtime
