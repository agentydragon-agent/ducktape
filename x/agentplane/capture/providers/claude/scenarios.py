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
    return submit(capture, "Reply with exactly: CAPTURE_BASELINE_OK", action="claude_baseline_prompt")


def submit(capture: NativeCapture, prompt: str, *, action: str) -> dict[str, Any]:
    """Send one native user frame and retain the raw provider terminal evidence."""
    frame = driver.user_frame(prompt)
    capture.write(frame, action=action)
    terminal = capture.await_frame(lambda item: item.get("type") == "result", timeout=120)
    return {"prompt_uuid": frame["uuid"], "terminal": terminal}


def session_id(submission: dict[str, Any]) -> str:
    terminal = submission.get("terminal")
    if not isinstance(terminal, dict) or not isinstance(terminal.get("session_id"), str):
        raise ValueError("Claude result did not return a durable session id")
    return terminal["session_id"]


def submit_while_active(capture: NativeCapture, *, scenario: str) -> dict[str, Any]:
    """Deliberately write a second user frame while a deterministic shell wait is active.

    Claude exposes user input as the same native shape for ordinary and policy-labelled
    steering probes.  The action labels, original UUIDs, and timing evidence preserve that
    fact rather than inventing a neutral operation.
    """
    first = driver.user_frame(
        "Use the Bash tool to run `python operation_probe.py wait --seconds 20`; after it finishes reply ONLY WAIT_DONE."
    )
    capture.write(first, action=f"claude_{scenario}_initial_wait")
    active = capture.await_frame(lambda item: item.get("type") == "stream_event", timeout=60)
    second = driver.user_frame("Reply ONLY SECOND_INPUT_OBSERVED after your current work.")
    capture.write(second, action=f"claude_{scenario}_second_user_frame")
    terminal = capture.await_frame(lambda item: item.get("type") == "result", timeout=120)
    return {"first_uuid": first["uuid"], "second_uuid": second["uuid"], "active_evidence": active, "terminal": terminal}


def interrupt(capture: NativeCapture, *, with_queued_input: bool) -> dict[str, Any]:
    first = driver.user_frame(
        "Use the Bash tool to run `python operation_probe.py wait --seconds 20`; do not answer early."
    )
    capture.write(first, action="claude_interrupt_initial_wait")
    active = capture.await_frame(lambda item: item.get("type") == "stream_event", timeout=60)
    queued_uuid = None
    if with_queued_input:
        queued = driver.user_frame("This is intentionally queued input; acknowledge only if admitted.")
        queued_uuid = queued["uuid"]
        capture.write(queued, action="claude_interrupt_queued_user_frame")
    request = driver.interrupt(cancel_queued=with_queued_input)
    capture.write(request, action="claude_interrupt_control_request")
    response = capture.await_frame(
        lambda item: (
            item.get("type") == "control_response"
            and item.get("response", {}).get("request_id") == request["request_id"]
        ),
        timeout=30,
    )
    terminal = capture.await_frame(lambda item: item.get("type") == "result", timeout=120)
    return {
        "initial_uuid": first["uuid"],
        "queued_uuid": queued_uuid,
        "active_evidence": active,
        "interrupt_response": response,
        "terminal": terminal,
    }


def command(binary: str, *, model: str, resume_id: str | None = None) -> list[str]:
    result = [
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
    if resume_id:
        result.extend(["--resume", resume_id])
    return result
