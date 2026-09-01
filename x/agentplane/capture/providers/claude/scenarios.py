"""Claude-specific live discovery scenarios, retaining its native control JSON."""

from __future__ import annotations

from typing import Any

from x.agentplane.capture.providers.claude import driver
from x.agentplane.capture.providers.shared_capture import NativeCapture


def launch_handshake(capture: NativeCapture) -> dict[str, Any]:
    frame = driver.initialize()
    capture.write(frame, action="claude_initialize")
    request_id = frame["request_id"]
    reply = capture.await_frame(
        lambda item: (
            item.get("type") == "control_response"
            and isinstance(item.get("response"), dict)
            and item["response"].get("request_id") == request_id
        ),
        timeout=30,
    )
    return {"initialize_request_id": request_id, "control_response": reply}


def baseline(capture: NativeCapture) -> dict[str, Any]:
    frame = driver.user_frame("Reply with exactly: CAPTURE_BASELINE_OK")
    capture.write(frame, action="claude_baseline_prompt")
    terminal = capture.await_frame(lambda item: item.get("type") == "result", timeout=120)
    return {"prompt_uuid": frame["uuid"], "terminal": terminal}


def command(binary: str, *, model: str) -> list[str]:
    return [
        binary,
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-mode",
        "bypassPermissions",
        "--include-partial-messages",
        "--input-format",
        "stream-json",
        "--model",
        model,
    ]
