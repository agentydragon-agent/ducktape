from __future__ import annotations

from adgn.agent.handler import BaseHandler, JsonlRecord, ToolCall, ToolCallOutput, to_jsonl_record

# TranscriptLoggerHandler removed; use TranscriptHandler from adgn.agent.transcript_handler instead.


class RecordingHandler(BaseHandler):
    """In-memory event recorder for tests.

    Collects selected events into `records` as JSON-serializable dicts using
    to_jsonl_record(). Keep lightweight and deterministic for unit tests.
    """

    def __init__(self) -> None:
        self.records: list[JsonlRecord] = []

    # Minimal subset used by tests; extend as needed
    def on_tool_call_event(self, evt: ToolCall) -> None:
        rec = to_jsonl_record(evt)
        self.records.append(rec)

    def on_tool_result_event(self, evt: ToolCallOutput) -> None:
        rec = to_jsonl_record(evt)
        self.records.append(rec)
