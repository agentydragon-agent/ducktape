from __future__ import annotations


from adgn.llm.mcp._shared.fastmcp_helpers import SafeFastMCP
from adgn.llm.mcp._shared.fastmcp_helpers import mcp_flat_model
from pydantic import BaseModel, ConfigDict

from adgn.llm.mini_codex.ui.shared_bus import UiMessage, UiEndTurn, UiBus
# UI MCP server: lightweight tools to instruct the HTML UI rendering layer.
# Tools are declarative; the agent can call them to emit UI messages and to
# explicitly end a turn (as a bus message).


class SendMessageInput(BaseModel):
    mime: str
    content: str
    model_config = ConfigDict(extra="forbid")


class EndTurnInput(BaseModel):
    """Empty input for end_turn (keeps single-arg typed pattern consistent)."""

    model_config = ConfigDict(extra="forbid")


def make_ui_mcp(name: str, bus: UiBus) -> SafeFastMCP:
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
        description="Send a message to the UI",
        structured_output=True,
    )
    def send_message(input: SendMessageInput) -> UiMessage:  # type: ignore[valid-type]
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
    def end_turn(input: EndTurnInput) -> UiEndTurn:  # type: ignore[valid-type]
        bus.push_end_turn()
        return UiEndTurn()

    # Expose the bus for wiring (agent factory can stash it)
    mcp._ui_bus = bus  # type: ignore[attr-defined]
    return mcp
