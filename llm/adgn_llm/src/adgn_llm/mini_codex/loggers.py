from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class TranscriptLogger:
    """Event hook that mirrors the conversation progressively.

    - Writes one JSON object per line to transcript.jsonl
    - Emits a structlog info event for each item (mini_codex_event)

    This object is intended to be registered as an on-event callback in MiniCodex.
    It is synchronous; callers can await it via a maybe_await wrapper.
    """

    def __init__(self, run_dir: Path) -> None:
        self._path = run_dir / "transcript.jsonl"

    def __call__(self, event: dict[str, Any]) -> None:
        # Single sink: append to JSONL transcript
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
