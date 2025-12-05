from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from adgn.agent.events import AssistantText, ToolCall, ToolCallOutput, UserText
from adgn.agent.handler import BaseHandler
from adgn.openai_utils.model import ReasoningItem


@dataclass
class _Event:
    ts: str
    kind: str
    payload: Any


class TranscriptHandler(BaseHandler):
    """Writes timestamped JSONL event stream to file."""

    def __init__(self, *, events_path: Path) -> None:
        self._path = events_path
        # Fail fast if a transcript already exists at destination
        if self._path.exists():
            raise FileExistsError(f"Transcript already exists: {self._path}")

    # ---- Event helpers ----
    def _write_event(self, evt: Any) -> None:
        # Create parent directory if needed (lazy initialization)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        rec = evt.model_dump(mode="json", exclude_none=True)
        # Timestamped envelope (events.jsonl)
        out = {"ts": datetime.now(UTC).isoformat(), **rec}
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(out, ensure_ascii=False) + "\n")

    # ---- BaseHandler hooks (typed) ----
    def on_user_text_event(self, evt: UserText) -> None:
        self._write_event(evt)

    def on_assistant_text_event(self, evt: AssistantText) -> None:
        self._write_event(evt)

    def on_tool_call_event(self, evt: ToolCall) -> None:
        self._write_event(evt)

    def on_tool_result_event(self, evt: ToolCallOutput) -> None:
        self._write_event(evt)

    def on_reasoning(self, item: ReasoningItem) -> None:
        self._write_event(item)

    def on_response(self, evt: Any) -> None:
        # Record one responses.create result per model call with usage
        self._write_event(evt)
