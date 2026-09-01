"""Explicit native Codex app-server JSON-RPC frame constructors."""

from __future__ import annotations

from typing import Any


def initialize(request_id: str) -> dict[str, Any]:
    return {
        "method": "initialize",
        "id": request_id,
        "params": {"clientInfo": {"name": "agentplane-capture", "version": "0.1"}, "capabilities": None},
    }


def initialized() -> dict[str, Any]:
    return {"method": "initialized"}


def thread_start(request_id: str, *, cwd: str, model: str, effort: str) -> dict[str, Any]:
    return {
        "method": "thread/start",
        "id": request_id,
        "params": {
            "cwd": cwd,
            "approvalPolicy": "never",
            "sandbox": "danger-full-access",
            "ephemeral": False,
            "model": model,
            "config": {"model_reasoning_effort": effort},
        },
    }


def turn_start(request_id: str, *, thread_id: str, text: str) -> dict[str, Any]:
    return {
        "method": "turn/start",
        "id": request_id,
        "params": {"threadId": thread_id, "input": [{"type": "text", "text": text, "text_elements": []}]},
    }


def steer(request_id: str, *, thread_id: str, turn_id: str, text: str) -> dict[str, Any]:
    return {
        "method": "turn/steer",
        "id": request_id,
        "params": {
            "threadId": thread_id,
            "turnId": turn_id,
            "input": [{"type": "text", "text": text, "text_elements": []}],
        },
    }


def interrupt(request_id: str, *, thread_id: str, turn_id: str) -> dict[str, Any]:
    return {"method": "turn/interrupt", "id": request_id, "params": {"threadId": thread_id, "turnId": turn_id}}
