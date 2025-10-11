from __future__ import annotations

from typing import Any

from adgn.agent.handler import (
    BaseHandler,
    ToolCall,
    ToolCallOutput,
    to_jsonl_record,
)

# TranscriptLoggerHandler removed; use TranscriptHandler from adgn.agent.transcript_handler instead.


class RecordingHandler(BaseHandler):
    """In-memory event recorder for tests.

    Collects selected events into `records` as JSON-serializable dicts using
    to_jsonl_record(). Keep lightweight and deterministic for unit tests.
    """

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    # Minimal subset used by tests; extend as needed
    def on_tool_call_event(self, evt: ToolCall) -> None:
        self.records.append(to_jsonl_record(evt))

    def on_tool_result_event(self, evt: ToolCallOutput) -> None:
        self.records.append(to_jsonl_record(evt))
