"""Test utility for agent event inspection."""

from __future__ import annotations

from adgn.agent.events import ToolCall, ToolCallOutput
from adgn.agent.handler import BaseHandler


class RecordingHandler(BaseHandler):
    """In-memory event recorder for tests."""

    def __init__(self) -> None:
        self.records: list[ToolCall | ToolCallOutput] = []

    # Minimal subset used by tests; extend as needed
    def on_tool_call_event(self, evt: ToolCall) -> None:
        self.records.append(evt)

    def on_tool_result_event(self, evt: ToolCallOutput) -> None:
        self.records.append(evt)
