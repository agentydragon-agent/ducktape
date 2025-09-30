from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Callable, Literal, Any, Union
from pydantic import BaseModel


class MimeType(StrEnum):
    """Supported MIME types for UI messages."""

    MARKDOWN = "text/markdown"
    # Future expansion could include:
    # HTML = "text/html"
    # PLAIN = "text/plain"


class UiMessage(BaseModel):
    mime: MimeType
    content: str


class UiEndTurn(BaseModel):
    """Control message: UI should end the assistant turn now."""

    kind: Literal["EndTurn"] = "EndTurn"


UiBusItem = Union[UiMessage, UiEndTurn]


@dataclass
class UiBus:
    """Process-local shared state between UI MCP server, handler, and UI bridge.

    - messages: append-only queue of UiBusItem objects for the UI to pull/render
    - end_turn_requested: sticky flag set by end_turn tool; consumed by handler/UI
    - is_end_turn: optional predicate set by the UI MCP server to recognize its end_turn tool
    """

    messages: list[UiBusItem] = field(default_factory=list)
    end_turn_requested: bool = False
    is_end_turn: Callable[[Any], bool] | None = None

    def push_message(self, msg: UiMessage) -> None:
        self.messages.append(msg)

    def push_end_turn(self) -> None:
        self.messages.append(UiEndTurn())
        self.end_turn_requested = True

    def drain_messages(self) -> list[UiBusItem]:
        out = list(self.messages)
        self.messages.clear()
        return out

    def consume_end_turn(self) -> bool:
        was = self.end_turn_requested
        self.end_turn_requested = False
        return was
