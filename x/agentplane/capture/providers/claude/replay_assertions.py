"""Behavioral assertions for Claude native replay evidence."""

from __future__ import annotations

import json
from typing import Any

from x.agentplane.capture.replay import ReplayServer

MODEL = "anthropic-max20/ant-messages/claude-haiku-4-5-20251001"


def assert_request_shape(server: ReplayServer) -> None:
    assert server.observed
    for observed in server.observed:
        body = json.loads(observed["body"])
        assert body["model"] == MODEL
        assert body["stream"] is True
        assert "messages" in body


def assert_small_policy(server: ReplayServer) -> None:
    for observed in server.observed:
        body = json.loads(observed["body"])
        for block in body.get("system", []):
            if isinstance(block, dict):
                assert len(block.get("text", "")) < 15_000


def result_text(submission: dict[str, Any]) -> str:
    terminal = submission["terminal"]
    assert isinstance(terminal, dict)
    result = terminal.get("result")
    assert isinstance(result, str), terminal
    return result


def frames(root: Any) -> list[dict[str, Any]]:
    records = (root / "capture" / "stdout.jsonl").read_text().splitlines()
    return [json.loads(json.loads(line)["text"]) for line in records]


def tool_uses(captured: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        item
        for frame in captured
        if frame.get("type") == "assistant"
        for item in frame.get("message", {}).get("content", [])
        if item.get("type") == "tool_use"
    ]


def tool_results(captured: list[dict[str, Any]]) -> list[Any]:
    return [
        frame["tool_use_result"] for frame in captured if frame.get("type") == "user" and "tool_use_result" in frame
    ]


def assistant_texts(captured: list[dict[str, Any]]) -> list[str]:
    return [
        item["text"]
        for frame in captured
        if frame.get("type") == "assistant"
        for item in frame.get("message", {}).get("content", [])
        if item.get("type") == "text" and isinstance(item.get("text"), str)
    ]


def terminal(captured: list[dict[str, Any]]) -> dict[str, Any]:
    terminals = [frame for frame in captured if frame.get("type") == "result"]
    assert terminals
    return terminals[-1]


def assert_tool_lifecycles(captured: list[dict[str, Any]], expected_names: list[str]) -> list[Any]:
    uses = tool_uses(captured)
    assert [item["name"] for item in uses] == expected_names
    stream_events = [
        frame["event"]
        for frame in captured
        if frame.get("type") == "stream_event" and isinstance(frame.get("event"), dict)
    ]
    assert sum(event.get("type") == "content_block_start" for event in stream_events) >= len(expected_names)
    assert sum(event.get("type") == "content_block_stop" for event in stream_events) >= len(expected_names)
    results = tool_results(captured)
    assert len(results) >= len(expected_names)
    return results


def assert_success(root: Any, expected: str) -> list[dict[str, Any]]:
    captured = frames(root)
    result = terminal(captured)
    assert result["is_error"] is False
    assert result["stop_reason"] == "end_turn"
    assert result["terminal_reason"] == "completed"
    assert result["result"] == expected
    assert expected in assistant_texts(captured)
    return captured


def assert_success_contains(root: Any, expected_fragment: str) -> list[dict[str, Any]]:
    captured = frames(root)
    result = terminal(captured)
    assert result["is_error"] is False
    assert result["stop_reason"] == "end_turn"
    assert result["terminal_reason"] == "completed"
    assert expected_fragment in result["result"]
    return captured


def assert_failure(root: Any, *, result_fragment: str, terminal_reason: str) -> list[dict[str, Any]]:
    captured = frames(root)
    result = terminal(captured)
    assert result["is_error"] is True
    assert result["terminal_reason"] == terminal_reason
    assert result_fragment in result.get("result", "")
    return captured
