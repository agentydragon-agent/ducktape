#!/usr/bin/env python3
import json
from pathlib import Path
from typing import Iterator, Optional, Any, List
import asyncio

TRACE_DIR = Path.home() / ".claude-code-router" / "logs"
OUTPUT_PATH = Path(__file__).rsplit("/", 1)[0]
OUTPUT_PATH = Path(OUTPUT_PATH) / "data" / "dataset.jsonl"

BAD_MARKER = "<bad>"
TOOLS_HEADER = "You can use the following tools without requiring user approval:"


def list_trace_files() -> List[Path]:
    if not TRACE_DIR.exists():
        return []
    return [p for p in sorted(TRACE_DIR.glob("trace.*")) if p.is_file()]


def find_last_user_text(msg: Any) -> Optional[str]:
    if not isinstance(msg, dict):
        return None
    if msg.get("role") != "user":
        return None
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                t = part.get("text")
                if isinstance(t, str):
                    texts.append(t)
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


async def process_file(p: Path) -> List[dict]:
    out: List[dict] = []
    try:
        # Use asyncio to read file without blocking CPU (still I/O bound)
        # Fall back to normal open for simplicity; large lines still ok
        with p.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except Exception:
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
                out.append({
                    "correlation_id": rec.get("correlationId"),
                    "timestamp": rec.get("timestamp"),
                    "anthropic_request": body,
                    "log_file": str(p),
                })
    except Exception:
        return out
    return out


async def main():
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    files = list_trace_files()
    sem = asyncio.Semaphore(16)

    async def wrapped(p: Path):
        async with sem:
            return await process_file(p)

    results: List[List[dict]] = await asyncio.gather(*[wrapped(p) for p in files])
    count = 0
    with OUTPUT_PATH.open("w", encoding="utf-8") as out:
        for batch in results:
            for dp in batch:
                out.write(json.dumps(dp, ensure_ascii=False) + "\n")
                count += 1
    print(f"wrote {count} samples -> {OUTPUT_PATH}")

if __name__ == "__main__":
    asyncio.run(main())
