"""Codex-specific live discovery scenarios, retaining native JSON-RPC semantics."""

from __future__ import annotations

from typing import Any

from x.agentplane.capture.providers.codex import driver
from x.agentplane.capture.providers.shared_capture import NativeCapture


def launch_handshake(capture: NativeCapture, *, cwd: str, model: str, effort: str) -> dict[str, Any]:
    initialize = driver.initialize("capture-1")
    capture.write(initialize, action="codex_initialize")
    init_response = capture.await_frame(lambda item: item.get("id") == "capture-1", timeout=30)
    capture.write(driver.initialized(), action="codex_initialized")
    start = driver.thread_start("capture-2", cwd=cwd, model=model, effort=effort)
    capture.write(start, action="codex_thread_start")
    started = capture.await_frame(lambda item: item.get("id") == "capture-2", timeout=30)
    return {"initialize_response": init_response, "thread_start_response": started}


def resume_handshake(capture: NativeCapture, *, thread_id: str) -> dict[str, Any]:
    """Initialize a fresh app-server process and load its on-disk thread."""
    capture.write(driver.initialize("capture-4"), action="codex_resume_initialize")
    init_response = capture.await_frame(lambda item: item.get("id") == "capture-4", timeout=30)
    capture.write(driver.initialized(), action="codex_resume_initialized")
    resume = driver.thread_resume("capture-5", thread_id=thread_id)
    capture.write(resume, action="codex_thread_resume")
    resumed = capture.await_frame(lambda item: item.get("id") == "capture-5", timeout=30)
    return {"initialize_response": init_response, "thread_resume_response": resumed, "thread_id": thread_id}


def baseline(capture: NativeCapture, *, thread_start_response: dict[str, Any]) -> dict[str, Any]:
    return submit(
        capture,
        thread_start_response=thread_start_response,
        text="Reply with exactly: CAPTURE_BASELINE_OK",
        action="codex_baseline_turn_start",
    )


def _thread_id(thread_start_response: dict[str, Any]) -> str:
    result = thread_start_response.get("result")
    if (
        not isinstance(result, dict)
        or not isinstance(result.get("thread"), dict)
        or not isinstance(result["thread"].get("id"), str)
    ):
        raise ValueError("Codex thread/start did not return a durable thread id")
    return result["thread"]["id"]


def submit(capture: NativeCapture, *, thread_start_response: dict[str, Any], text: str, action: str) -> dict[str, Any]:
    thread_id = _thread_id(thread_start_response)
    return submit_to_thread(capture, thread_id=thread_id, request_id="capture-3", text=text, action=action)


def submit_to_thread(
    capture: NativeCapture, *, thread_id: str, request_id: str, text: str, action: str
) -> dict[str, Any]:
    start = driver.turn_start(request_id, thread_id=thread_id, text=text)
    capture.write(start, action=action)
    started = capture.await_frame(lambda item: item.get("id") == request_id, timeout=30)
    turn_result = started.get("result")
    if (
        not isinstance(turn_result, dict)
        or not isinstance(turn_result.get("turn"), dict)
        or not isinstance(turn_result["turn"].get("id"), str)
    ):
        raise ValueError("Codex turn/start did not return a turn id")
    turn_id = turn_result["turn"]["id"]
    terminal = capture.await_frame(
        lambda item: item.get("method") == "turn/completed" and isinstance(item.get("params"), dict), timeout=120
    )
    return {"thread_id": thread_id, "turn_id": turn_id, "terminal": terminal}


def submit_while_active(
    capture: NativeCapture, *, thread_start_response: dict[str, Any], scenario: str
) -> dict[str, Any]:
    thread_id = _thread_id(thread_start_response)
    initial = driver.turn_start(
        "capture-3",
        thread_id=thread_id,
        text="Use shell to run `python operation_probe.py wait --seconds 20`; do not answer early.",
    )
    capture.write(initial, action=f"codex_{scenario}_initial_turn_start")
    started = capture.await_frame(lambda item: item.get("id") == "capture-3", timeout=30)
    turn_id = started["result"]["turn"]["id"]
    active = capture.await_frame(lambda item: item.get("method") == "turn/started", timeout=30)
    if scenario == "steering":
        followup = driver.steer(
            "capture-4", thread_id=thread_id, turn_id=turn_id, text="Reply ONLY STEERED after the current tool action."
        )
        action = "codex_steering_turn_steer"
    else:
        followup = driver.turn_start(
            "capture-4", thread_id=thread_id, text="Reply ONLY SECOND_INPUT_OBSERVED after current work."
        )
        action = f"codex_{scenario}_second_turn_start"
    capture.write(followup, action=action)
    response = capture.await_frame(lambda item: item.get("id") == "capture-4", timeout=30)
    terminal = capture.await_frame(lambda item: item.get("method") == "turn/completed", timeout=120)
    return {
        "thread_id": thread_id,
        "turn_id": turn_id,
        "active_evidence": active,
        "followup_response": response,
        "terminal": terminal,
    }


def interrupt(
    capture: NativeCapture, *, thread_start_response: dict[str, Any], with_queued_input: bool
) -> dict[str, Any]:
    thread_id = _thread_id(thread_start_response)
    start = driver.turn_start(
        "capture-3",
        thread_id=thread_id,
        text="Use shell to run `python operation_probe.py wait --seconds 20`; do not answer early.",
    )
    capture.write(start, action="codex_interrupt_initial_turn_start")
    started = capture.await_frame(lambda item: item.get("id") == "capture-3", timeout=30)
    turn_id = started["result"]["turn"]["id"]
    active = capture.await_frame(lambda item: item.get("method") == "turn/started", timeout=30)
    queued_response = None
    if with_queued_input:
        queued = driver.turn_start("capture-4", thread_id=thread_id, text="Queued input: reply only if admitted.")
        capture.write(queued, action="codex_interrupt_queued_turn_start")
        queued_response = capture.await_frame(lambda item: item.get("id") == "capture-4", timeout=30)
    request = driver.interrupt("capture-5", thread_id=thread_id, turn_id=turn_id)
    capture.write(request, action="codex_interrupt_turn_interrupt")
    response = capture.await_frame(lambda item: item.get("id") == "capture-5", timeout=30)
    terminal = capture.await_frame(lambda item: item.get("method") == "turn/completed", timeout=120)
    return {
        "thread_id": thread_id,
        "turn_id": turn_id,
        "active_evidence": active,
        "queued_response": queued_response,
        "interrupt_response": response,
        "terminal": terminal,
    }


def command(binary: str, *, endpoint: str) -> list[str]:
    # This config is direct native app-server setup, not a Haku adapter. The environment
    # supplies OPENAI_API_KEY; the model provider shape keeps the Responses endpoint explicit.
    provider = 'model_provider = "agentplane"'
    providers = (
        'model_providers = {agentplane = {name = "Agentplane LiteLLM", '
        f'base_url = "{endpoint}", env_key = "OPENAI_API_KEY", wire_api = "responses"}}}}'
    )
    return [binary, "-c", provider, "-c", providers, "app-server", "--listen", "stdio://"]
