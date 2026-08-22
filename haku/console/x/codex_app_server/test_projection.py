from pathlib import Path

import pytest_bazel

from haku.console.chat_models import ItemType, ReasoningDisclosure, ToolOutcome, TurnOutcome
from haku.console.x.codex_app_server.projection import ProjectionState, RecordedFrame, project, project_log
from haku.console.x.codex_app_server.protocol import read_trace, server_messages
from haku.console.x.conversation_events import (
    CallRef,
    FrameRange,
    ItemSegment,
    MessageCompleted,
    MessageStarted,
    OpenRef,
    ReasoningCompleted,
    ReasoningStarted,
    ToolCallCompleted,
    ToolCallStarted,
    TurnCompleted,
)
from util.bazel.runfiles import get_required_path

_FIXTURE = "haku/console/x/codex_app_server/testdata/schema_derived_turn.synthetic.jsonl"
_MESSAGE = OpenRef(item_type=ItemType.MESSAGE)
_REASONING = OpenRef(item_type=ItemType.REASONING)


def frames() -> tuple[RecordedFrame, ...]:
    source_path = Path(_FIXTURE)
    path = source_path if source_path.exists() else get_required_path(f"ducktape/{_FIXTURE}")
    return tuple(RecordedFrame(record.seq, record.message) for record in server_messages(read_trace(path)))


def test_schema_derived_fixture_projects_the_supported_surface():
    projection = project_log(frames())

    assert projection.events == (
        ReasoningStarted(provenance=FrameRange(10, 10)),
        ItemSegment(item=_REASONING, text="Inspecting ", provenance=FrameRange(11, 11)),
        ItemSegment(item=_REASONING, text="the request.", provenance=FrameRange(12, 12)),
        ReasoningCompleted(disclosure=ReasoningDisclosure.SUMMARY, provenance=FrameRange(10, 13)),
        MessageStarted(provenance=FrameRange(14, 14)),
        ItemSegment(item=_MESSAGE, text="Done", provenance=FrameRange(15, 15)),
        ItemSegment(item=_MESSAGE, text=".", provenance=FrameRange(16, 16)),
        MessageCompleted(backend_item_id="<ITEM_2>", provenance=FrameRange(14, 16)),
        ToolCallStarted(
            call_id="<ITEM_3>",
            tool_name="commandExecution",
            arguments={"command": "printf ok", "cwd": "<WORKSPACE>"},
            provenance=FrameRange(17, 17),
        ),
        ItemSegment(item=CallRef(call_id="<ITEM_3>"), text="ok\n", provenance=FrameRange(18, 18)),
        ToolCallCompleted(
            item=CallRef(call_id="<ITEM_3>"),
            structured={
                "command": "printf ok",
                "cwd": "<WORKSPACE>",
                "processId": None,
                "source": "agent",
                "status": "completed",
                "commandActions": [],
                "exitCode": 0,
                "durationMs": 5,
            },
            outcome=ToolOutcome.SUCCEEDED,
            provenance=FrameRange(19, 19),
        ),
        ToolCallStarted(
            call_id="<ITEM_4>", tool_name="fixture/echo", arguments={"text": "hello"}, provenance=FrameRange(20, 20)
        ),
        ItemSegment(item=CallRef(call_id="<ITEM_4>"), text="tool ok", provenance=FrameRange(22, 22)),
        ToolCallCompleted(
            item=CallRef(call_id="<ITEM_4>"),
            structured={
                "server": "fixture",
                "tool": "echo",
                "status": "completed",
                "appContext": None,
                "pluginId": None,
                "result": {
                    "content": [{"type": "text", "text": "tool ok"}],
                    "structuredContent": {"echoed": True},
                    "_meta": None,
                },
                "error": None,
                "durationMs": 7,
            },
            outcome=ToolOutcome.SUCCEEDED,
            provenance=FrameRange(22, 22),
        ),
        TurnCompleted(outcome=TurnOutcome.ANSWERED, provenance=FrameRange(25, 25)),
    )
    assert projection.unprojected == {"item/started/futureThing": 1, "future/notification": 1}


def test_every_batching_and_reprojection_of_the_fixture_is_identical():
    native = frames()
    expected = project_log(native)
    assert project_log(native) == expected
    assert project_log(native) == expected

    for split in range(len(native) + 1):
        state, first = project(ProjectionState(), native[:split])
        state, second = project(state, native[split:])
        assert state == ProjectionState()
        assert first.then(second) == expected


def test_malformed_and_unknown_notifications_fail_softly():
    projection = project_log(
        (
            RecordedFrame(1, {"method": "item/started", "params": {"item": {"type": "agentMessage"}}}),
            RecordedFrame(2, {"method": "item/agentMessage/delta", "params": []}),
            RecordedFrame(3, {"method": "brand/new", "params": {"value": 1}}),
        )
    )
    assert projection.events == ()
    assert projection.unprojected == {"item/started/identity": 1, "item/agentMessage/delta/params": 1, "brand/new": 1}


def test_nonterminal_and_duplicate_tool_completions_fail_softly():
    item: dict[str, object] = {
        "type": "commandExecution",
        "id": "call-1",
        "command": "printf ok",
        "cwd": "<WORKSPACE>",
        "processId": None,
        "source": "agent",
        "commandActions": [],
        "aggregatedOutput": None,
        "exitCode": 0,
        "durationMs": 5,
    }
    projection = project_log(
        (
            RecordedFrame(1, {"method": "item/started", "params": {"item": {**item, "status": "inProgress"}}}),
            RecordedFrame(2, {"method": "item/completed", "params": {"item": {**item, "status": "inProgress"}}}),
            RecordedFrame(3, {"method": "item/completed", "params": {"item": {**item, "status": "completed"}}}),
            RecordedFrame(4, {"method": "item/completed", "params": {"item": {**item, "status": "completed"}}}),
        )
    )

    assert [type(event) for event in projection.events] == [ToolCallStarted, ToolCallCompleted]
    assert projection.unprojected == {
        "item/completed/commandExecution/status": 1,
        "item/completed/commandExecution/duplicate": 1,
    }


if __name__ == "__main__":
    pytest_bazel.main()
