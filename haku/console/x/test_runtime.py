"""Focused contracts for Console runtime selection."""

from __future__ import annotations

from typing import cast

import pytest
import pytest_bazel

from haku.console.chat_models import RuntimeKind
from haku.console.x.claude_code import projection
from haku.console.x.claude_code.testing.wire import assistant, recorded, text_block
from haku.console.x.runtime import UnsupportedRuntimeError
from haku.console.x.runtime_catalog import projection_registry
from haku.runtime.x.bridge.protocol import HarnessFrame


def test_projection_registry_exposes_each_linked_provider_adapter() -> None:
    registry = projection_registry()

    assert registry.kinds == frozenset({RuntimeKind.CLAUDE_CODE, RuntimeKind.CODEX_APP_SERVER})
    assert registry[RuntimeKind.CLAUDE_CODE].kind is RuntimeKind.CLAUDE_CODE
    assert registry[RuntimeKind.CODEX_APP_SERVER].kind is RuntimeKind.CODEX_APP_SERVER


def test_registry_fails_closed_for_a_runtime_kind_that_is_not_registered() -> None:
    registry = projection_registry()

    with pytest.raises(UnsupportedRuntimeError, match="not registered"):
        registry[cast(RuntimeKind, "future_runtime")]


def test_runtime_adapter_keeps_claude_projection_behavior_unchanged() -> None:
    payload = assistant(text_block("hello"), message_id="msg_1")
    adapter = projection_registry()[RuntimeKind.CLAUDE_CODE]

    through_adapter = adapter.turn_handler().apply(frame_seq=7, frame=HarnessFrame(frame=payload)).events
    through_native = projection.project(
        projection.ProjectionState(), [recorded(7, payload)], delta_source=projection.DeltaSource.STREAM_EVENTS
    )[1].events

    assert through_adapter == through_native


def test_claude_adapter_keeps_opaque_native_frames_inspectable() -> None:
    adapter = projection_registry()[RuntimeKind.CLAUDE_CODE]
    payload = {"jsonrpc": "2.0", "method": "future/event", "params": {"opaque": True}}
    undiscriminated = {"jsonrpc": "2.0", "id": 1, "result": {}}

    effects = adapter.turn_handler().apply(frame_seq=8, frame=HarnessFrame(frame=payload))
    whole = adapter.project_log([(8, HarnessFrame(frame=payload)), (9, HarnessFrame(frame=undiscriminated))])

    assert effects.events == ()
    assert whole.events == ()
    assert whole.unprojected == {"future/event": 1, "<undiscriminated>": 1}


if __name__ == "__main__":
    pytest_bazel.main()
