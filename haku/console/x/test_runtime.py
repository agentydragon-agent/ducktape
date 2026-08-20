"""Focused contracts for Console runtime selection."""

from __future__ import annotations

from typing import cast

import pytest
import pytest_bazel

from haku.console.chat_models import RuntimeKind
from haku.console.x.claude_code import projection
from haku.console.x.claude_code.testing.wire import assistant, recorded, text_block
from haku.console.x.conversation_events import ProjectionState
from haku.console.x.runtime import RuntimeRegistry, UnsupportedRuntimeError


def test_registry_exposes_only_the_registered_claude_runtime() -> None:
    registry = RuntimeRegistry.projection_only()

    assert registry.kinds == frozenset({RuntimeKind.CLAUDE_CODE})
    assert registry[RuntimeKind.CLAUDE_CODE].kind is RuntimeKind.CLAUDE_CODE


def test_registry_fails_closed_for_a_runtime_kind_that_is_not_registered() -> None:
    registry = RuntimeRegistry.projection_only()

    with pytest.raises(UnsupportedRuntimeError, match="not registered"):
        registry[cast(RuntimeKind, "future_runtime")]


def test_runtime_adapter_keeps_claude_projection_behavior_unchanged() -> None:
    payload = assistant(text_block("hello"), message_id="msg_1")
    adapter = RuntimeRegistry.projection_only()[RuntimeKind.CLAUDE_CODE]

    through_adapter = adapter.project_frame(ProjectionState(), frame_seq=7, payload=payload)[1]
    through_native = projection.project(
        ProjectionState(), [recorded(7, payload)], delta_source=projection.DeltaSource.STREAM_EVENTS
    )[1].events

    assert through_adapter == through_native


def test_claude_adapter_keeps_opaque_native_frames_inspectable() -> None:
    adapter = RuntimeRegistry.projection_only()[RuntimeKind.CLAUDE_CODE]
    state = ProjectionState()
    payload = {"jsonrpc": "2.0", "method": "future/event", "params": {"opaque": True}}
    frame = {"kind": "claude", "payload": payload}
    undiscriminated = {"kind": "claude", "payload": {"jsonrpc": "2.0", "id": 1, "result": {}}}

    folded, events = adapter.project_frame(state, frame_seq=8, payload=payload)
    whole = adapter.project_log([(8, frame), (9, undiscriminated)])

    assert folded == state
    assert events == ()
    assert whole.events == ()
    assert whole.unprojected == {"future/event": 1, "<undiscriminated>": 1}


if __name__ == "__main__":
    pytest_bazel.main()
