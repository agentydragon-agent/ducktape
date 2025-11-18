from __future__ import annotations

from collections.abc import Callable, Iterator
import gzip
import json
from pathlib import Path
from typing import Any, TextIO

from pydantic import TypeAdapter

from .constants import TOOLS_HEADER
from .openai_typing import (
    MessageRole,
    ResponseContentPart,
    iter_resolved_text,
    parse_response_messages,
    response_message_content_as_text,
    response_message_role,
)


def join_text_parts(content: Any) -> str:
    """Normalize OpenAI-style content into plain text.

    Accepts either a string or a list of parts like {type: "text", text: "..."}.
    Returns a single string (possibly empty).
    """
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    parts = TypeAdapter(list[ResponseContentPart]).validate_python(content)
    return "\n".join(iter_resolved_text(parts))


def sys_has_tools_header(system: Any) -> bool:
    """Return True if system text (string or list-of-parts) contains tools header."""
    if isinstance(system, str):
        return TOOLS_HEADER in system
    if system is None:
        return False
    parts = TypeAdapter(list[ResponseContentPart]).validate_python(system)
    return any(TOOLS_HEADER in text for text in iter_resolved_text(parts))


def find_last_user_text_from_msg(msg: Any) -> str | None:
    """Extract plain text from a single user message object (CCR-style)."""
    if response_message_role(msg) != MessageRole.USER:
        return None
    text = response_message_content_as_text(msg)
    return text or None


def find_last_user_text_from_messages(messages: Any) -> str | None:
    """Extract last user text from a list of messages (OpenAI chat/Responses)."""
    parsed = parse_response_messages(messages)
    if parsed:
        last = parsed[-1]
        if response_message_role(last) == MessageRole.USER:
            text = response_message_content_as_text(last)
            return text or None
        return None
    if not isinstance(messages, list) or not messages:
        return None
    last = messages[-1]
    if isinstance(last, dict) and (last.get("role") or "").lower() == "user":
        text = join_text_parts(last.get("content"))
        return text or None
    return None


def iter_wire_lines(path: Path) -> Iterator[str]:
    """Yield lines from a possibly gzipped file; ignore encoding errors."""
    if not path.exists():
        return

    def _gzip_open(p: Path) -> TextIO:
        return gzip.open(p, "rt", encoding="utf-8", errors="ignore")

    def _plain_open(p: Path) -> TextIO:
        return p.open(encoding="utf-8", errors="ignore")

    opener: Callable[[Path], TextIO] = _gzip_open if str(path).endswith(".gz") else _plain_open
    with opener(path) as f:
        yield from f


def maybe_extract_payload(obj: dict[str, Any]) -> dict[str, Any] | None:
    """Return embedded provider payload dict when present (Crush wire logs)."""
    p = obj.get("payload")
    return p if isinstance(p, dict) else None


# ---------------------------------------------------------------------------
# Shared helpers for dataset extraction scripts
# ---------------------------------------------------------------------------


def write_jsonl_batches(results: list[list[dict]], output_path: Path, *, event: str) -> None:
    """Write a 2D list of JSON-serializable dicts to a JSONL file and emit a summary.

    - results: list of batches (each batch is a list of dict records)
    - output_path: destination file path
    - event: event name to include in the summary line printed to stdout
    """
    count = 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as out:
        for batch in results:
            for dp in batch:
                out.write(json.dumps(dp, ensure_ascii=False) + "\n")
                count += 1
    print(json.dumps({"event": event, "count": count, "path": str(output_path)}))
