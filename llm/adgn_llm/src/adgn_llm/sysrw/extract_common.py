from __future__ import annotations

import gzip
from pathlib import Path
from typing import Any, Iterator

from .constants import TOOLS_HEADER


def join_text_parts(content: Any) -> str:
    """Normalize OpenAI-style content into plain text.

    Accepts either a string or a list of parts like {type: "text", text: "..."}.
    Returns a single string (possibly empty).
    """
    if isinstance(content, str):
        return content
    texts: list[str] = []
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                t = part.get("text")
                if isinstance(t, str):
                    texts.append(t)
    return "\n".join(texts) if texts else ""


def sys_has_tools_header(system: Any) -> bool:
    """Return True if system text (string or list-of-parts) contains tools header."""
    if isinstance(system, str):
        return TOOLS_HEADER in system
    if isinstance(system, list):
        for item in system:
            if isinstance(item, dict) and item.get("type") == "text":
                t = item.get("text")
                if isinstance(t, str) and TOOLS_HEADER in t:
                    return True
    return False


def find_last_user_text_from_msg(msg: Any) -> str | None:
    """Extract plain text from a single user message object (CCR-style)."""
    if not isinstance(msg, dict):
        return None
    if (msg.get("role") or "").lower() != "user":
        return None
    text = join_text_parts(msg.get("content"))
    return text or None


def find_last_user_text_from_messages(messages: Any) -> str | None:
    """Extract last user text from a list of messages (OpenAI chat/Responses)."""
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

    def _gzip_open(p: Path):
        return gzip.open(p, "rt", encoding="utf-8", errors="ignore")

    def _plain_open(p: Path):
        return open(p, encoding="utf-8", errors="ignore")

    opener = _gzip_open if str(path).endswith(".gz") else _plain_open
    with opener(path) as f:  # type: ignore[misc]
        for line in f:
            yield line


def maybe_extract_payload(obj: dict[str, Any]) -> dict[str, Any] | None:
    """Return embedded provider payload dict when present (Crush wire logs)."""
    p = obj.get("payload")
    return p if isinstance(p, dict) else None
