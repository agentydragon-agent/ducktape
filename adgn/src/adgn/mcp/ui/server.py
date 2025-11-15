from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from adgn.agent.server.bus import MimeType, ServerBus, UiEndTurn, UiMessage
from adgn.mcp._shared.constants import UI_SERVER_NAME
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP

# UI MCP server: lightweight tools to instruct the HTML UI rendering layer.
# Tools are declarative; the agent can call them to emit UI messages and to
# explicitly end a turn (as a bus message).


class SendMessageInput(BaseModel):
    mime: Annotated[
        MimeType,
        Field(
            description="MIME type for the message content. Currently only 'text/markdown' is supported. "
            "Use markdown formatting for rich text (headers, lists, code blocks, etc.)."
        ),
    ] = MimeType.MARKDOWN
    content: Annotated[
        str,
        Field(
            description="The message content to display in the UI. Supports full markdown syntax including "
            "code blocks, lists, tables, and inline formatting."
        ),
    ]
    model_config = ConfigDict(extra="forbid")


class EndTurnInput(BaseModel):
    """Empty input for end_turn (keeps single-arg typed pattern consistent)."""

    model_config = ConfigDict(extra="forbid")


def make_ui_server(name: str, bus: ServerBus) -> NotifyingFastMCP:
    mcp = NotifyingFastMCP(
        name,
        instructions=(
            "UI helper: send formatted messages and end your turn via tools.\n"
            "Do not emit plain text in this UI; always use the UI tools."
        ),
    )

    # Typed inputs (flat schema)
    @mcp.flat_model()
    def send_message(input: SendMessageInput) -> UiMessage:
        """Send a formatted message to the UI (markdown recommended)."""
        msg = UiMessage(mime=input.mime, content=input.content)
        bus.push_message(msg)
        return msg

    @mcp.flat_model()
    def end_turn(input: EndTurnInput) -> UiEndTurn:
        """Tell the UI to end the current turn."""
        bus.push_end_turn()
        return UiEndTurn()

    # Return the server; callers keep their own reference to the bus.
    return mcp


async def attach_ui(comp: Compositor, bus: ServerBus, *, name: str = UI_SERVER_NAME) -> NotifyingFastMCP:
    """Attach the UI MCP server in-proc to a Compositor (preferred path)."""
    server = make_ui_server(name, bus)
    await comp.mount_inproc(name, server)
    return server
