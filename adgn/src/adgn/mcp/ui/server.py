from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from adgn.agent.server.bus import MimeType, ServerBus, UiEndTurn, UiMessage
from adgn.mcp._shared.fastmcp_helpers import SafeFastMCP, mcp_flat_model

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


def make_ui_mcp(name: str, bus: ServerBus) -> SafeFastMCP:
    mcp = SafeFastMCP(
        name,
        instructions=(
            "UI helper server: use send_message to communicate with the user and end_turn to finish your turn.\n"
            "Contract: In this UI, assistant does not emit plain text. You MUST use ui.send_message (text/markdown) for output,\n"
            "and call ui.end_turn when you are done."
        ),
    )

    # Typed inputs (flat schema)
    @mcp_flat_model(
        mcp,
        name="send_message",
        title="Send UI message",
        description="Send a formatted message to the UI. Use markdown formatting for rich text display.",
        structured_output=True,
    )
    def send_message(input: SendMessageInput) -> UiMessage:
        msg = UiMessage(mime=input.mime, content=input.content)
        bus.push_message(msg)
        return msg

    @mcp_flat_model(
        mcp,
        name="end_turn",
        title="End UI turn",
        description="Tell the UI to end the current turn",
        structured_output=True,
    )
    def end_turn(input: EndTurnInput) -> UiEndTurn:
        bus.push_end_turn()
        return UiEndTurn()

    # Return the server; callers keep their own reference to the bus.
    return mcp
