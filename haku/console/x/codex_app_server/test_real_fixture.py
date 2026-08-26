from pathlib import Path

import pytest_bazel

from haku.console.chat_models import ItemType, ReasoningDisclosure, ToolOutcome, TurnOutcome
from haku.console.x.codex_app_server.projection import RecordedFrame, project_log
from haku.console.x.codex_app_server.protocol import read_trace, server_messages
from haku.console.x.codex_app_server.runtime import CodexRuntimeAdapter
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
from haku.runtime.x.bridge.protocol import HarnessFrame
from util.bazel.runfiles import get_required_path

_SUCCESS_FIXTURE = "haku/console/x/codex_app_server/testdata/real_text_command.sanitized.jsonl"
_HIGH_DEMAND_FIXTURE = "haku/console/x/codex_app_server/testdata/real_high_demand_failure.sanitized.jsonl"
_MESSAGE = OpenRef(item_type=ItemType.MESSAGE)


def _fixture_path(fixture: str) -> Path:
    source = Path(fixture)
    return source if source.exists() else get_required_path(f"ducktape/{fixture}")


def _frames(fixture: str) -> tuple[RecordedFrame, ...]:
    return tuple(
        RecordedFrame(record.seq, record.message) for record in server_messages(read_trace(_fixture_path(fixture)))
    )


def test_real_capture_projects_both_observed_turn_lifecycles():
    projection = project_log(_frames(_SUCCESS_FIXTURE))

    assert projection.events == (
        MessageStarted(provenance=FrameRange(12, 12)),
        ItemSegment(item=_MESSAGE, text="TRACE", provenance=FrameRange(13, 13)),
        ItemSegment(item=_MESSAGE, text="_TEXT", provenance=FrameRange(14, 14)),
        ItemSegment(item=_MESSAGE, text="_OK", provenance=FrameRange(15, 15)),
        MessageCompleted(backend_item_id="<protocol-id-4>", provenance=FrameRange(12, 16)),
        TurnCompleted(outcome=TurnOutcome.ANSWERED, provenance=FrameRange(17, 17)),
        ReasoningStarted(provenance=FrameRange(23, 23)),
        ReasoningCompleted(disclosure=ReasoningDisclosure.SUMMARY, provenance=FrameRange(23, 24)),
        ToolCallStarted(
            call_id="exec-<protocol-id-8>",
            tool_name="commandExecution",
            arguments={"command": "<ABSOLUTE_PATH> -c 'printf TRACE_CMD_OK'", "cwd": "<WORKSPACE>"},
            provenance=FrameRange(25, 25),
        ),
        ToolCallCompleted(
            item=CallRef(call_id="exec-<protocol-id-8>"),
            structured={
                "command": "<ABSOLUTE_PATH> -c 'printf TRACE_CMD_OK'",
                "cwd": "<WORKSPACE>",
                "processId": "<process-id>",
                "source": "unifiedExecStartup",
                "status": "completed",
                "commandActions": [{"type": "unknown", "command": "printf TRACE_CMD_OK"}],
                "exitCode": 0,
                "durationMs": 0,
            },
            outcome=ToolOutcome.SUCCEEDED,
            provenance=FrameRange(26, 26),
        ),
        MessageStarted(provenance=FrameRange(27, 27)),
        ItemSegment(item=_MESSAGE, text="TRACE", provenance=FrameRange(28, 28)),
        ItemSegment(item=_MESSAGE, text="_COMMAND", provenance=FrameRange(29, 29)),
        ItemSegment(item=_MESSAGE, text="_DONE", provenance=FrameRange(30, 30)),
        MessageCompleted(backend_item_id="<protocol-id-9>", provenance=FrameRange(27, 31)),
        TurnCompleted(outcome=TurnOutcome.ANSWERED, provenance=FrameRange(32, 32)),
    )
    assert projection.unprojected == {}


def test_real_high_demand_capture_becomes_a_neutral_failure() -> None:
    handler = CodexRuntimeAdapter().turn_handler()
    completions = []
    for record in server_messages(read_trace(_fixture_path(_HIGH_DEMAND_FIXTURE))):
        effects = handler.apply(frame_seq=record.seq, frame=HarnessFrame(frame=record.message))
        if effects.completion is not None:
            completions.append(effects.completion)

    assert len(completions) == 1
    completion = completions[0]
    assert completion.outcome is TurnOutcome.FAILED
    assert completion.final_text == ""
    assert completion.failure == (
        "the agent's turn failed: We're currently experiencing high demand, which may cause temporary errors."
    )


if __name__ == "__main__":
    pytest_bazel.main()
