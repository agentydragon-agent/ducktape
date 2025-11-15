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
from adgn.mcp.testing.server_stubs import ServerStub


class EditorServerStub(ServerStub):
    """Typed stub for editor server operations."""

    async def read_info(self, input: ReadInfoArgs) -> ReadInfoResult: ...
    async def read_line_range(self, input: ReadLineRangeArgs) -> ReadLineRangeResult: ...
    async def replace_text(self, input: ReplaceTextArgs) -> ReplaceTextResult: ...
    async def replace_text_all(self, input: ReplaceTextAllArgs) -> ReplaceTextAllResult: ...
    async def delete_line(self, input: DeleteLineArgs) -> DeleteLineResult: ...
    async def add_line_after(self, input: AddLineAfterArgs) -> AddLineAfterResult: ...
    async def save(self, input: SaveArgs) -> SaveResult: ...
    async def done(self, input: DoneInput) -> DoneResponse: ...
