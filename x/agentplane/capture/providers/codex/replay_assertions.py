"""Behavioral assertions for Codex native replay evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from x.agentplane.capture.providers.codex import driver
from x.agentplane.capture.replay import ReplayServer

MODEL = "chatgpt/oai-responses/gpt-5.6-luna"


def assert_request_shape(server: ReplayServer) -> None:
    assert server.observed
    for observed in server.observed:
        body = json.loads(observed["body"])
        assert body["model"] == MODEL
        assert body["stream"] is True
        assert "input" in body


def assert_prompt_is_capture_scoped(server: ReplayServer) -> None:
    assert server.observed
    for observed in server.observed:
        body = json.loads(observed["body"])
        assert body["instructions"] == driver.BASE_INSTRUCTIONS
        serialized = observed["body"].decode("utf-8")
        assert "<skills_instructions>" not in serialized
        assert "<permissions instructions>" not in serialized
        assert "<apps_instructions>" not in serialized
        assert "<collaboration_mode>" not in serialized
        assert "<environment_context>" not in serialized


def result_text(submission: dict[str, Any]) -> str:
    terminal = submission["terminal"]
    assert isinstance(terminal, dict)
    items = terminal["params"]["turn"]["items"]
    assert items, terminal
    text = items[-1]["text"]
    assert isinstance(text, str)
    return text


def frames(root: Path) -> list[dict[str, Any]]:
    records = (root / "capture" / "stdout.jsonl").read_text().splitlines()
    return [json.loads(json.loads(line)["text"]) for line in records]


def items(captured: list[dict[str, Any]], *, item_type: str | None = None) -> list[dict[str, Any]]:
    result = []
    for frame in captured:
        if frame.get("method") not in {"item/started", "item/completed"}:
            continue
        item = frame.get("params", {}).get("item")
        if isinstance(item, dict) and (item_type is None or item.get("type") == item_type):
            result.append(item)
    return result


def completed_turns(captured: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        frame["params"]["turn"]
        for frame in captured
        if frame.get("method") == "turn/completed" and isinstance(frame.get("params", {}).get("turn"), dict)
    ]


def agent_texts(captured: list[dict[str, Any]]) -> list[str]:
    return [
        item["text"]
        for item in items(captured, item_type="agentMessage")
        if isinstance(item.get("text"), str) and item["text"]
    ]


def assert_success(root: Path, expected: str) -> list[dict[str, Any]]:
    captured = frames(root)
    turns = completed_turns(captured)
    assert turns
    assert turns[-1]["status"] == "completed"
    assert agent_texts(captured)[-1] == expected
    assert expected in agent_texts(captured)
    return captured


def assert_success_contains(root: Path, expected_fragment: str) -> list[dict[str, Any]]:
    captured = frames(root)
    turns = completed_turns(captured)
    assert turns
    assert turns[-1]["status"] == "completed"
    assert expected_fragment in agent_texts(captured)[-1]
    return captured


def assert_item_lifecycles(captured: list[dict[str, Any]], item_type: str) -> list[dict[str, Any]]:
    started = {
        item["id"]
        for frame in captured
        if frame.get("method") == "item/started"
        for item in [frame.get("params", {}).get("item")]
        if isinstance(item, dict) and item.get("type") == item_type and item.get("id")
    }
    completed = [
        item
        for frame in captured
        if frame.get("method") == "item/completed"
        for item in [frame.get("params", {}).get("item")]
        if isinstance(item, dict) and item.get("type") == item_type
    ]
    assert completed
    assert all(item.get("id") in started for item in completed)
    return completed
