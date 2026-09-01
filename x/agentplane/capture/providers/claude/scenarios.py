"""Claude-specific live discovery scenarios, retaining its native control JSON."""

from __future__ import annotations

from typing import Any

from x.agentplane.capture.providers.claude import driver
from x.agentplane.capture.providers.shared_capture import NativeCapture


def launch_handshake(capture: NativeCapture) -> dict[str, Any]:
    frame = driver.initialize()
    capture.write(frame)
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
    return submit(capture, "Reply with exactly: CAPTURE_BASELINE_OK")


def submit(capture: NativeCapture, prompt: str) -> dict[str, Any]:
    """Send one native user frame and retain the raw provider terminal evidence."""
    frame = driver.user_frame(prompt)
    capture.write(frame)
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
    steering probes. The original UUIDs and native timing evidence preserve that fact
    without adding a second, driver-authored action log.
    """
    first = driver.user_frame(
        'Use the Bash tool to run `sh -c \'printf "wait_started\\n"; sleep 20; '
        'printf "wait_finished\\n"\'`; after it finishes reply ONLY WAIT_DONE.'
    )
    capture.write(first)
    active = capture.await_frame(lambda item: item.get("type") == "stream_event", timeout=60)
    second = driver.user_frame("Reply ONLY SECOND_INPUT_OBSERVED after your current work.")
    capture.write(second)
    terminal = capture.await_frame(lambda item: item.get("type") == "result", timeout=120)
    return {"first_uuid": first["uuid"], "second_uuid": second["uuid"], "active_evidence": active, "terminal": terminal}


def interrupt(capture: NativeCapture, *, with_queued_input: bool) -> dict[str, Any]:
    first = driver.user_frame(
        'Use the Bash tool to run `sh -c \'printf "wait_started\\n"; sleep 20; '
        'printf "wait_finished\\n"\'`; do not answer early.'
    )
    capture.write(first)
    active = capture.await_frame(lambda item: item.get("type") == "stream_event", timeout=60)
    queued_uuid = None
    if with_queued_input:
        queued = driver.user_frame("This is intentionally queued input; acknowledge only if admitted.")
        queued_uuid = queued["uuid"]
        capture.write(queued)
    request = driver.interrupt(cancel_queued=with_queued_input)
    capture.write(request)
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
        # Captures need the native harness, not this machine's installed skills,
        # plugins, hooks, or project instructions. Keep the tools the explicit
        # scenarios exercise and make the saved request bodies tractable.
        "--safe-mode",
        "--disable-slash-commands",
        "--tools",
        "Bash,Read,Edit,Write",
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
