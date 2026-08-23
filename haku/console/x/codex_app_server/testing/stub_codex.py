"""A small Codex app-server stand-in for the real-runner end-to-end test."""

from __future__ import annotations

import json
import os
import re
import select
import sys
from pathlib import Path
from typing import Any

_DIRECTIVE = re.compile(r"\s*\[(hold)\]")


def _send(frame: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(frame) + "\n")
    sys.stdout.flush()


def _response(request: dict[str, Any], result: Any) -> None:
    _send({"id": request["id"], "result": result})


def _error(request: dict[str, Any], message: str) -> None:
    _send({"id": request["id"], "error": {"code": -32000, "message": message}})


def _text(request: dict[str, Any]) -> str:
    return "".join(
        str(item.get("text", ""))
        for item in request.get("params", {}).get("input", [])
        if isinstance(item, dict) and item.get("type") == "text"
    )


def _completed(turn_id: str, status: str = "completed") -> None:
    _send(
        {
            "method": "turn/completed",
            "params": {"threadId": "thread-1", "turn": {"id": turn_id, "status": status, "error": None}},
        }
    )


def main() -> None:
    state = Path(os.environ["HAKU_STUB_STATE"])
    if (greeting := os.environ.get("HAKU_STUB_GREETING")) is not None:
        print(greeting, file=sys.stderr, flush=True)

    initialized = False
    answered = 0
    held: tuple[str, Path, Path] | None = None
    while True:
        if held is not None and held[2].exists():
            turn_id, asked, release = held
            release.unlink()
            asked.unlink()
            _completed(turn_id)
            held = None

        readable, _, _ = select.select([sys.stdin], [], [], 0.05)
        if not readable:
            continue
        line = sys.stdin.readline()
        if not line:
            return
        request = json.loads(line)
        method = request.get("method")
        if method == "thread/loaded/list":
            if not initialized:
                _error(request, "Not initialized")
            else:
                _response(request, {"data": ["thread-1"], "nextCursor": None})
        elif method == "thread/read":
            turns = [] if held is None else [{"id": held[0], "status": "inProgress", "items": []}]
            _response(request, {"thread": {"id": "thread-1", "turns": turns}})
        elif method == "initialize":
            if initialized:
                _error(request, "Already initialized")
            else:
                initialized = True
                _response(request, {"userAgent": "stub-codex/0.144.1"})
        elif method == "initialized":
            pass
        elif method == "thread/start":
            with (state / "system-prompts.jsonl").open("a") as recorded:
                recorded.write(json.dumps(request.get("params", {}).get("developerInstructions")) + "\n")
            _response(request, {"thread": {"id": "thread-1"}})
            _send({"method": "thread/started", "params": {"thread": {"id": "thread-1"}}})
        elif method == "turn/start":
            answered += 1
            turn_id = f"turn-{answered}"
            body = _text(request).strip().splitlines()[-1]
            text = f"re: {_DIRECTIVE.sub('', body).strip()}"
            _response(request, {"turn": {"id": turn_id, "status": "inProgress", "items": []}})
            _send(
                {
                    "method": "item/started",
                    "params": {
                        "threadId": "thread-1",
                        "turnId": turn_id,
                        "item": {"type": "agentMessage", "id": f"message-{answered}"},
                    },
                }
            )
            _send(
                {
                    "method": "item/agentMessage/delta",
                    "params": {
                        "threadId": "thread-1",
                        "turnId": turn_id,
                        "itemId": f"message-{answered}",
                        "delta": text,
                    },
                }
            )
            _send(
                {
                    "method": "item/completed",
                    "params": {
                        "threadId": "thread-1",
                        "turnId": turn_id,
                        "item": {"type": "agentMessage", "id": f"message-{answered}", "text": text},
                    },
                }
            )
            if "hold" in _DIRECTIVE.findall(body):
                asked, release = state / "asked", state / "release"
                asked.write_text(text)
                held = (turn_id, asked, release)
                _send({"method": "haku/stubHeld", "params": {"turnId": turn_id}})
            else:
                _completed(turn_id)
        elif method == "turn/interrupt":
            _response(request, {})
            turn_id = request.get("params", {}).get("turnId")
            if isinstance(turn_id, str):
                _completed(turn_id, "interrupted")
                held = None
        elif "id" in request:
            _error(request, f"unsupported method: {method}")


if __name__ == "__main__":
    main()
