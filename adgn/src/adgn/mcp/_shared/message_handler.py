"""Typed async MessageHandler protocol for MCP notifications.

fastmcp's MessageHandler has synchronous methods, but our handlers need async.
This protocol provides proper typing for async message handlers without type: ignore suppressions.
"""

from __future__ import annotations

from typing import Protocol

from mcp import types as mcp_types
from mcp.shared.session import RequestResponder


class AsyncMessageHandler(Protocol):
    """Async protocol for MCP message handlers.

    Provides properly typed async methods for handling MCP notifications and requests.
    Unlike fastmcp's MessageHandler (which has sync methods), this protocol supports
    async handlers without requiring type: ignore suppressions.

    Handlers only need to implement the methods they care about; unimplemented methods
    are ignored (protocol doesn't require all methods).
    """

    async def on_cancelled(self, message: mcp_types.CancelledNotification) -> None:
        """Handle cancellation notification."""
        ...

    async def on_create_message(self, message: mcp_types.CreateMessageRequest) -> None:
        """Handle create message request."""
        ...

    async def on_exception(self, message: Exception) -> None:
        """Handle exception."""
        ...

    async def on_list_roots(self, message: mcp_types.ListRootsRequest) -> None:
        """Handle list roots request."""
        ...

    async def on_logging_message(self, message: mcp_types.LoggingMessageNotification) -> None:
        """Handle logging message notification."""
        ...

    async def on_message(
        self,
        message: RequestResponder[mcp_types.ServerRequest, mcp_types.ClientResult]
        | mcp_types.ServerNotification
        | Exception,
    ) -> None:
        """Handle any message."""
        ...

    async def on_notification(self, message: mcp_types.ServerNotification) -> None:
        """Handle server notification."""
        ...

    async def on_ping(self, message: mcp_types.PingRequest) -> None:
        """Handle ping request."""
        ...

    async def on_progress(self, message: mcp_types.ProgressNotification) -> None:
        """Handle progress notification."""
        ...

    async def on_prompt_list_changed(self, message: mcp_types.PromptListChangedNotification) -> None:
        """Handle prompt list changed notification."""
        ...

    async def on_request(
        self, message: RequestResponder[mcp_types.ServerRequest, mcp_types.ClientResult]
    ) -> None:
        """Handle server request."""
        ...

    async def on_resource_list_changed(self, message: mcp_types.ResourceListChangedNotification) -> None:
        """Handle resource list changed notification."""
        ...

    async def on_resource_updated(self, message: mcp_types.ResourceUpdatedNotification) -> None:
        """Handle resource updated notification."""
        ...

    async def on_tool_list_changed(self, message: mcp_types.ToolListChangedNotification) -> None:
        """Handle tool list changed notification."""
        ...
