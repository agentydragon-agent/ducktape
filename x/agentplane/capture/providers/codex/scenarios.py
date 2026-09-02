"""Codex-specific live discovery scenarios, retaining native JSON-RPC semantics."""

from __future__ import annotations

from contextlib import suppress
from typing import Any

from x.agentplane.capture.providers.codex import driver
from x.agentplane.capture.providers.shared_capture import NativeCapture


def launch_handshake(
    capture: NativeCapture, *, cwd: str, model: str, effort: str, persist: bool = False
) -> dict[str, Any]:
    initialize = driver.initialize("capture-1")
    capture.write(initialize)
    init_response = capture.await_frame(lambda item: item.get("id") == "capture-1", timeout=30)
    capture.write(driver.initialized())
    start = driver.thread_start("capture-2", cwd=cwd, model=model, effort=effort, persist=persist)
    capture.write(start)
    started = capture.await_frame(lambda item: item.get("id") == "capture-2", timeout=30)
    return {"initialize_response": init_response, "thread_start_response": started}


def resume_handshake(capture: NativeCapture, *, thread_id: str) -> dict[str, Any]:
    """Initialize a fresh app-server process and load its on-disk thread."""
    capture.write(driver.initialize("capture-4"))
    init_response = capture.await_frame(lambda item: item.get("id") == "capture-4", timeout=30)
    capture.write(driver.initialized())
    resume = driver.thread_resume("capture-5", thread_id=thread_id)
    capture.write(resume)
    resumed = capture.await_frame(lambda item: item.get("id") == "capture-5", timeout=30)
    return {"initialize_response": init_response, "thread_resume_response": resumed, "thread_id": thread_id}


def baseline(capture: NativeCapture, *, thread_start_response: dict[str, Any]) -> dict[str, Any]:
    return submit(capture, thread_start_response=thread_start_response, text="Reply with exactly: CAPTURE_BASELINE_OK")


def _thread_id(thread_start_response: dict[str, Any]) -> str:
    result = thread_start_response.get("result")
    thread = result.get("thread") if isinstance(result, dict) else None
    thread_id_value = thread.get("id") if isinstance(thread, dict) else None
    if not isinstance(thread_id_value, str):
        raise ValueError("Codex thread/start did not return a durable thread id")
    return thread_id_value


def submit(capture: NativeCapture, *, thread_start_response: dict[str, Any], text: str) -> dict[str, Any]:
    thread_id = _thread_id(thread_start_response)
    return submit_to_thread(capture, thread_id=thread_id, request_id="capture-3", text=text)


def submit_to_thread(capture: NativeCapture, *, thread_id: str, request_id: str, text: str) -> dict[str, Any]:
    start = driver.turn_start(request_id, thread_id=thread_id, text=text)
    capture.write(start)
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
        text=(
            'Use shell to run `sh -c \'printf "wait_started\\n"; sleep 20; '
            'printf "wait_finished\\n"\'`; do not answer early.'
        ),
    )
    capture.write(initial)
    started = capture.await_frame(lambda item: item.get("id") == "capture-3", timeout=30)
    turn_id = started["result"]["turn"]["id"]
    active = capture.await_frame(lambda item: item.get("method") == "turn/started", timeout=30)
    if scenario == "steering":
        followup = driver.steer(
            "capture-4", thread_id=thread_id, turn_id=turn_id, text="Reply ONLY STEERED after the current tool action."
        )
    else:
        followup = driver.turn_start(
            "capture-4", thread_id=thread_id, text="Reply ONLY SECOND_INPUT_OBSERVED after current work."
        )
    capture.write(followup)
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
        text=(
            'Use shell to run `sh -c \'printf "wait_started\\n"; sleep 20; '
            'printf "wait_finished\\n"\'`; do not answer early.'
        ),
    )
    capture.write(start)
    started = capture.await_frame(lambda item: item.get("id") == "capture-3", timeout=30)
    turn_id = started["result"]["turn"]["id"]
    # Codex can accept an interrupt before it emits a native turn/started event when
    # the mocked upstream has no request for this scenario.
    active = None
    with suppress(TimeoutError):
        active = capture.await_frame(lambda item: item.get("method") == "turn/started", timeout=1)
    queued_response = None
    if with_queued_input:
        queued = driver.turn_start("capture-4", thread_id=thread_id, text="Queued input: reply only if admitted.")
        capture.write(queued)
        queued_response = capture.await_frame(lambda item: item.get("id") == "capture-4", timeout=30)
    request = driver.interrupt("capture-5", thread_id=thread_id, turn_id=turn_id)
    capture.write(request)
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
    # Remove automatic skill discovery and its <skills_instructions> prompt block.
    skills = "skills = { bundled = { enabled = false }, include_instructions = false }"
    # These captures use a fixed native approval policy, so omit its redundant permissions
    # instructions rather than recording policy prose beside every tool description.
    permissions_instructions = "include_permissions_instructions = false"
    # These captures do not use app, collaboration, or environment-context features, so omit
    # their corresponding prompt blocks instead of recording unrelated harness guidance.
    app_instructions = "include_apps_instructions = false"
    collaboration_instructions = "include_collaboration_mode_instructions = false"
    environment_context = "include_environment_context = false"
    return [
        binary,
        "-c",
        provider,
        "-c",
        providers,
        "-c",
        skills,
        "-c",
        permissions_instructions,
        "-c",
        app_instructions,
        "-c",
        collaboration_instructions,
        "-c",
        environment_context,
        "app-server",
        "--listen",
        "stdio://",
    ]
