from __future__ import annotations

import json
from pathlib import Path

from adgn_llm.mini_codex.handler import (
    BaseHandler,
    UserText,
    AssistantText,
    ToolCall,
    FunctionCallOutput,
    Response,
    JsonlRecord,
    to_jsonl_record,
)


class TranscriptLoggerHandler(BaseHandler):
    """Typed handler that writes one JSONL record per event."""

    def __init__(self, run_dir: Path) -> None:
        self._path = run_dir / "transcript.jsonl"

    def _write(self, rec: JsonlRecord) -> None:
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Typed hook implementations
    def on_response(self, evt: Response) -> None:  # type: ignore[override]
        self._write(to_jsonl_record(evt))

    def on_user_text_event(self, evt: UserText) -> None:  # type: ignore[override]
        self._write(to_jsonl_record(evt))

    def on_assistant_text_event(self, evt: AssistantText) -> None:  # type: ignore[override]
        self._write(to_jsonl_record(evt))

    def on_tool_call_event(self, evt: ToolCall) -> None:  # type: ignore[override]
        self._write(to_jsonl_record(evt))

    def on_function_call_output_event(self, evt: FunctionCallOutput) -> None:  # type: ignore[override]
        self._write(to_jsonl_record(evt))
