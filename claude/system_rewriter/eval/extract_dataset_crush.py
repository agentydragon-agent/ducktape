#!/usr/bin/env python3
"""
Extract a CCR-like dataset from Crush provider wire logs without touching the
existing dataset.jsonl used by eval.

- Inputs:
  * Single file: --wire-log PATH (or env CRUSH_WIRE_LOG)
  * Scan mode: --scan-dir DIR (repeatable); finds **/.crush/logs/provider-wire.log under these roots
- Output: ./data/dataset_crush.jsonl (one JSON object per line)
  Does NOT overwrite ./data/dataset.jsonl

Selection logic (mirrors CCR extractor heuristics where possible):
- Only consider provider wire records where direction == "request"
- Expect payload to be an OpenAI Chat/Responses request (messages/system)
- Keep samples where:
  * System includes the tools header string, and
  * The last user message contains the BAD_MARKER token "<bad>"

Each output record has shape:
{
  "correlation_id": str | null,   # message_id or session_id from wire
  "timestamp": int | null,        # epoch millis parsed from RFC3339 ts
  "oai_request": { ... },         # original request payload captured by Crush
  "wirelog": {                    # minimal provenance/debug
      "event_type": str,          # e.g. chat.completions.new_streaming
      "path": ".../provider-wire.log"
  }
}
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from pydantic import ValidationError
from openai.types.responses import ResponseCreateParams
ROOT = Path(__file__).parent
DEFAULT_CRUSH_DIR = Path.home() / "code" / "crush"
DEFAULT_WIRE_LOG = Path(os.environ.get("CRUSH_WIRE_LOG", "")) if os.environ.get("CRUSH_WIRE_LOG") else (Path.home() / ".crush" / "logs" / "provider-wire.log")
OUTPUT_PATH = ROOT / "data" / "dataset_crush.jsonl"

from constants import BAD_MARKER, TOOLS_HEADER


def parse_rfc3339_millis(ts: str | None) -> int | None:
    if not ts or not isinstance(ts, str):
        return None
    try:
        # Support fractional seconds
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


def find_last_user_text_msg(messages: Any) -> str | None:
    if not isinstance(messages, list) or not messages:
        return None
    last = messages[-1]
    # OpenAI chat format
    if isinstance(last, dict) and last.get("role") == "user":
        content = last.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts: list[str] = []
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


def iter_wire_lines(path: Path):
    if not path.exists():
        return
    opener = None
    if str(path).endswith(".gz"):
        import gzip  # lazy import
        opener = lambda p: gzip.open(p, "rt", encoding="utf-8", errors="ignore")
    else:
        opener = lambda p: open(p, "r", encoding="utf-8", errors="ignore")
    with opener(path) as f:
        for line in f:
            yield line


def maybe_extract_payload(obj: dict[str, Any]) -> dict[str, Any] | None:
    # Crush logs payload under key "payload"; for requests this is the OpenAI Responses params
    p = obj.get("payload")
    return p if isinstance(p, dict) else None


def _extract_input_messages(payload: dict[str, Any]) -> tuple[list[dict[str, Any]] | None, bool]:
    """Best-effort extraction of system/user messages from OpenAI Responses params.
    Returns (messages, has_tools_header)."""
    inp = payload.get("input")
    if not isinstance(inp, list):
        return None, False
    msgs: list[dict[str, Any]] = []
    has_header = False
    for item in inp:
        if not isinstance(item, dict):
            continue
        role = (item.get("role") or item.get("message_role") or item.get("Role") or "").lower()
        content = item.get("content")
        # Extract text from either string or list-of-parts
        if isinstance(content, str):
            text = content
        else:
            texts: list[str] = []
            if isinstance(content, list):
                for c in content:
                    if isinstance(c, dict):
                        # Typical shape: {"type": "input_text", "text": "..."}
                        t = c.get("text") or c.get("input_text") or c.get("content")
                        if isinstance(t, str):
                            texts.append(t)
            text = "\n".join(texts) if texts else ""
        # Heuristic: if role missing, assume leading items are system until we see a 'user' later
        if not role:
            role = "system" if not any(m.get("role") == "user" for m in msgs) else "assistant"
        if role in ("system", "user", "assistant") and text:
            if role == "system" and TOOLS_HEADER in text:
                has_header = True
            msgs.append({"role": role, "content": text})
    return (msgs if msgs else None), has_header


def process_wire(path: Path, require_bad: bool = False) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in iter_wire_lines(path):
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("direction") != "request":
            continue
        payload = maybe_extract_payload(e)
        if not payload:
            continue
        # Validate into typed ResponsesRequest (let it crash on invalid)
        rr = ResponseCreateParams.model_validate(payload)
        # Reconstruct user messages to check for BAD marker
        messages, has_header = _extract_input_messages(payload)
        last_text = find_last_user_text_msg(messages)
        if not has_header:
            continue
        if require_bad and (not last_text or BAD_MARKER not in last_text):
            continue
        out.append(
            {
                "timestamp": parse_rfc3339_millis(e.get("ts")),
                "oai_request": rr.model_dump(mode="json"),
                "wirelog": {
                    "event_type": e.get("event_type"),
                    "path": str(path),
                },
            }
        )
    return out


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Extract dataset from Crush provider wire logs")
    ap.add_argument(
        "--wire-log",
        type=Path,
        default=DEFAULT_WIRE_LOG,
        help="Path to provider-wire.log (overrides scan mode)",
    )
    ap.add_argument(
        "--scan-dir",
        action="append",
        type=Path,
        default=[],
        help="Scan DIR recursively for **/.crush/logs/provider-wire.log (repeatable)",
    )
    ap.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_PATH,
        help="Output JSONL path (default: ./data/dataset_crush.jsonl)",
    )
    return ap.parse_args()


def find_wire_logs(roots: list[Path]) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        # Match current and rotated files, including .gz
        for globpat in ("provider-wire.log", "provider-wire.log.*", "provider-wire.*.log", "provider-wire.*.log.gz"):
            for p in root.rglob(globpat):
                try:
                    if ".crush/logs" in str(p.parent):
                        found.append(p)
                except Exception:
                    continue
    # Dedup and sort
    uniq = sorted({p.resolve() for p in found})
    return uniq


def main() -> int:
    args = parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    logs: list[Path] = []
    if args.wire_log and isinstance(args.wire_log, Path) and str(args.wire_log):
        logs = [args.wire_log]
    else:
        roots = args.scan_dir or [Path.home() / "code"]
        logs = find_wire_logs(roots)

    total = 0
    with args.output.open("w", encoding="utf-8") as out:
        for log_path in logs:
            recs = process_wire(log_path, require_bad=True)
            for r in recs:
                out.write(json.dumps(r, ensure_ascii=False) + "\n")
            total += len(recs)
    print(
        json.dumps(
            {
                "event": "dataset_crush_written",
                "count": total,
                "path": str(args.output),
                "files_scanned": len(logs)
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
