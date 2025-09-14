from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from adgn_llm.mini_codex.aggregating_handler import BaseHandler
from adgn_llm.mini_codex.loop_control import NoLoopDecision


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
    def _append(self, kind: str, payload: Any) -> None:
        ev = _Event(ts=datetime.utcnow().isoformat() + "Z", kind=kind, payload=payload)
        with self._events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(ev), ensure_ascii=False) + "\n")

    # ---- BaseHandler hooks ----
    def on_user_text(self, text: str) -> None:  # type: ignore[override]
        self._append("user_text", {"text": text})

    def on_assistant_text(self, text: str) -> None:  # type: ignore[override]
        self._append("assistant_text", {"text": text})

    def on_tool_call(self, call: Any) -> None:  # type: ignore[override]
        try:
            payload = (
                call
                if isinstance(call, dict)
                else {
                    "name": getattr(call, "name", None),
                    "type": getattr(call, "type", None),
                    "call_id": getattr(call, "call_id", None),
                    "arguments": getattr(call, "arguments", None),
                }
            )
        except Exception:
            payload = {"repr": repr(call)}
        self._append("tool_call", payload)

    def on_function_call_output(self, call: Any, output: Any) -> None:  # type: ignore[override]
        # Record only a small summary to keep logs readable
        try:
            name = getattr(call, "name", None) or getattr(call, "type", None)
            summary = str(output)
            if isinstance(summary, str) and len(summary) > 2000:
                summary = summary[:2000] + "..."
            payload = {"call": name, "output": summary}
        except Exception:
            payload = {"repr": repr(output)}
        self._append("tool_output", payload)

    def on_reasoning(self, item: Any) -> None:  # type: ignore[override]
        # Optional: keep as-is; callers can extend to capture richer content
        self._append("reasoning", {"repr": repr(item)})

    def on_before_sample(self) -> NoLoopDecision:  # type: ignore[override]
        # Do not influence loop control
        return NoLoopDecision()
