from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from adgn.agent.handler import AssistantText, BaseHandler, ToolCall, ToolCallOutput, UserText, to_jsonl_record
from adgn.agent.loop_control import NoLoopDecision
from adgn.openai_utils.model import ReasoningItem


@dataclass
class _Event:
    ts: str
    kind: str
    payload: Any


class TranscriptHandler(BaseHandler):
    """Unified transcript writer for MiniCodex runs.

    Writes a JSONL stream to the specified events file path.
    Each record is timestamped: {"ts": ISO8601, ...to_jsonl_record(evt)...}

    The parent directory must already exist (created by run managers).

    Usage:
      h = TranscriptHandler(events_path=run_dir / "events.jsonl")
      MiniCodex.create(..., handlers=[h, ...])
    """

    def __init__(self, *, events_path: Path) -> None:
        self._events_path = events_path
        # Create parent directory if needed
        self._events_path.parent.mkdir(parents=True, exist_ok=True)
        # Fail fast if a transcript already exists at destination
        if self._events_path.exists():
            raise FileExistsError(f"Transcript already exists: {self._events_path}")

    # ---- Event helpers ----
    def _write_event(self, evt: Any) -> None:
        rec = to_jsonl_record(evt)
        # Timestamped envelope (events.jsonl)
        out = {"ts": datetime.now(UTC).isoformat(), **rec}
        with self._events_path.open("a", encoding="utf-8") as f:
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
        # Record adapter ReasoningItem via shared JSONL mapping
        self._write_event(item)

    def on_response(self, evt: Any) -> None:
        # Record one responses.create result per model call with usage
        self._write_event(evt)

    def on_before_sample(self) -> NoLoopDecision:
        # Do not influence loop control
        return NoLoopDecision()
