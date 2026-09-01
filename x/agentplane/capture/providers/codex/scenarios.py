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


def baseline(capture: NativeCapture, *, thread_start_response: dict[str, Any]) -> dict[str, Any]:
    result = thread_start_response.get("result")
    if (
        not isinstance(result, dict)
        or not isinstance(result.get("thread"), dict)
        or not isinstance(result["thread"].get("id"), str)
    ):
        raise ValueError("Codex thread/start did not return a durable thread id")
    thread_id = result["thread"]["id"]
    start = driver.turn_start("capture-3", thread_id=thread_id, text="Reply with exactly: CAPTURE_BASELINE_OK")
    capture.write(start, action="codex_baseline_turn_start")
    started = capture.await_frame(lambda item: item.get("id") == "capture-3", timeout=30)
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


def command(binary: str, *, endpoint: str) -> list[str]:
    # This config is direct native app-server setup, not a Haku adapter. The environment
    # supplies OPENAI_API_KEY; the model provider shape keeps the Responses endpoint explicit.
    provider = 'model_provider = "agentplane"'
    providers = (
        'model_providers = {agentplane = {name = "Agentplane LiteLLM", '
        f'base_url = "{endpoint}", env_key = "OPENAI_API_KEY", wire_api = "responses"}}}}'
    )
    return [binary, "-c", provider, "-c", providers, "app-server", "--listen", "stdio://"]
