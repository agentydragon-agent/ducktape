#!/usr/bin/env python3
"""
Extract a CCR-like dataset from Claude Code router logs.

- Input: ~/.claude-code-router/logs/trace.*
- Output: ./data/dataset_ccr.jsonl (one JSON object per line)

Selection logic:
- Only consider inbound_request events that carry Anthropic-style body
- Keep samples where:
  * System includes the tools header string (constants.TOOLS_HEADER), and
  * The last user message contains the BAD_MARKER token "<bad>"

Each output record has shape:
{
  "correlation_id": str | null,
  "timestamp": int | null,
  "anthropic_request": CCRRequest,
  "log_file": path
}
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

TRACE_DIR = Path.home() / ".claude-code-router" / "logs"
OUTPUT_PATH = Path(__file__).parent / "data" / "dataset_ccr.jsonl"

from constants import BAD_MARKER, TOOLS_HEADER


def list_trace_files() -> list[Path]:
    if not TRACE_DIR.exists():
        return []
    return [p for p in sorted(TRACE_DIR.glob("trace.*")) if p.is_file()]


def find_last_user_text(msg: Any) -> str | None:
    if not isinstance(msg, dict):
        return None
    if msg.get("role") != "user":
        return None
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = [
            part.get("text")
            for part in content
            if isinstance(part, dict)
            and part.get("type") == "text"
            and isinstance(part.get("text"), str)
        ]
        return "\n".join(texts) if texts else None
    return None


def sys_has_tools_header(system: Any) -> bool:
    if isinstance(system, str):
        return TOOLS_HEADER in system
    if isinstance(system, list):
        for item in system:
            if isinstance(item, dict) and item.get("type") == "text":
                t = item.get("text")
                if isinstance(t, str) and TOOLS_HEADER in t:
                    return True
    return False


async def process_file(p: Path) -> list[dict]:
    out: list[dict] = []
    try:
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("event") != "inbound_request":
                    continue
                body = rec.get("body")
                if not isinstance(body, dict):
                    continue
                if not sys_has_tools_header(body.get("system")):
                    continue
                messages = body.get("messages")
                if not isinstance(messages, list) or not messages:
                    continue
                # Strict: marker must appear in the last message, and that last message must be a user text message
                last_msg = messages[-1]
                last_text = find_last_user_text(last_msg)
                if not last_text or BAD_MARKER not in last_text:
                    continue
                out.append(
                    {
                        "correlation_id": rec.get("correlationId"),
                        "timestamp": rec.get("timestamp"),
                        "anthropic_request": body,
                        "log_file": str(p),
                    }
                )
    except OSError:
        return out
    return out


async def main():
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    files = list_trace_files()
    sem = asyncio.Semaphore(16)

    async def wrapped(p: Path):
        async with sem:
            return await process_file(p)

    results: list[list[dict]] = await asyncio.gather(*[wrapped(p) for p in files])
    count = 0
    with OUTPUT_PATH.open("w", encoding="utf-8") as out:
        for batch in results:
            for dp in batch:
                out.write(json.dumps(dp, ensure_ascii=False) + "\n")
                count += 1
    print(
        json.dumps(
            {"event": "dataset_ccr_written", "count": count, "path": str(OUTPUT_PATH)}
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
