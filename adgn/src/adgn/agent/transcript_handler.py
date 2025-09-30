from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any
from adgn.openai_utils.model import ReasoningItem

from adgn.agent.handler import (
    AssistantText,
    BaseHandler,
    ToolCallOutput,
    ToolCall,
    UserText,
    to_jsonl_record,
)
from adgn.agent.loop_control import NoLoopDecision


@dataclass
class _Event:
    ts: str
    kind: str
    payload: Any


class TranscriptHandler(BaseHandler):
    """Simple JSONL transcript writer for MiniCodex runs.

    Writes events.jsonl under a destination directory with one JSON object per line:
    {"ts": ISO8601, "kind": <event>, "payload": {...}}

    Usage:
      h = TranscriptHandler(dest_dir=Path("runs/prompt_eval/<ts>/<specimen>/grader"))
      MiniCodex.create(..., handlers=[h, ...])
    """

    def __init__(self, *, dest_dir: Path) -> None:
        self._root = dest_dir
        self._root.mkdir(parents=True, exist_ok=True)
        self._events_path = self._root / "events.jsonl"
        # Fail fast if a transcript already exists at destination
        if self._events_path.exists():
            raise FileExistsError(f"Transcript already exists: {self._events_path}")
        # Write a small metadata file once
        (self._root / "metadata.json").write_text(
            json.dumps({"started": datetime.utcnow().isoformat() + "Z"}, indent=2),
            encoding="utf-8",
        )

    # ---- Event helpers ----
    def _write_event(self, evt: Any) -> None:
        rec = to_jsonl_record(evt)
        out = {"ts": datetime.utcnow().isoformat() + "Z", **rec}
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

    def on_before_sample(self) -> NoLoopDecision:
        # Do not influence loop control
        return NoLoopDecision()
