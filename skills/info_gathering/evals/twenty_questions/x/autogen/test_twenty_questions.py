"""Tests for Twenty Questions AutoGen v0.4 core runtime implementation.

Uses ReplayChatCompletionClient to run real agents with scripted model
responses through the autogen_core runtime.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import pytest_bazel
from autogen_core import FunctionCall
from autogen_core.models import CreateResult, RequestUsage
from autogen_ext.models.replay import ReplayChatCompletionClient

from skills.info_gathering.evals.twenty_questions.x.autogen.twenty_questions import run_game
from skills.info_gathering.evals.twenty_questions.x.shared.result_types import RunSummary

_ZERO_USAGE = RequestUsage(prompt_tokens=0, completion_tokens=0)


def _text_reply(text: str) -> CreateResult:
    """Build a CreateResult that returns plain text (for the guesser)."""
    return CreateResult(finish_reason="stop", content=text, usage=_ZERO_USAGE, cached=False)


def _tool_call_reply(name: str, arguments: dict[str, object]) -> CreateResult:
    """Build a CreateResult with a single function call (for the simulator)."""
    return CreateResult(
        finish_reason="function_calls",
        content=[FunctionCall(id="call_1", name=name, arguments=json.dumps(arguments))],
        usage=_ZERO_USAGE,
        cached=False,
    )


def _answer_reply(response: str) -> CreateResult:
    return _tool_call_reply("answer", {"response": response})


def _correct_reply() -> CreateResult:
    return _tool_call_reply("correct_answer", {})


@pytest.fixture
def _patch_prompts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "skills.info_gathering.evals.twenty_questions.x.autogen.twenty_questions.load_sim_prompt",
        MagicMock(return_value="You are the simulator."),
    )
    monkeypatch.setattr(
        "skills.info_gathering.evals.twenty_questions.x.autogen.twenty_questions.load_skill_prompt",
        MagicMock(return_value="You are skilled."),
    )


async def _run_with_replay(
    *, completions: list[CreateResult], tmp_path: Path, variant_name: str = "states"
) -> RunSummary:
    """Run a game with a ReplayChatCompletionClient providing scripted responses.

    The completions list should interleave guesser and simulator responses:
    [guesser_1, simulator_1, guesser_2, simulator_2, ...]
    """
    client = ReplayChatCompletionClient(
        chat_completions=completions,
        model_info={
            "vision": False,
            "function_calling": True,
            "json_output": False,
            "family": "unknown",
            "structured_output": False,
        },
    )
    return await run_game(
        variant_name=variant_name, model="test-model", api="openai", output_dir=tmp_path, model_client=client
    )


@pytest.mark.usefixtures("_patch_prompts")
async def test_correct_guess(tmp_path: Path) -> None:
    """Guesser guesses correctly on turn 2."""
    summary = await _run_with_replay(
        completions=[
            _text_reply("Is it a place?"),
            _answer_reply("yes"),
            _text_reply("My answer is: New Mexico"),
            _correct_reply(),
        ],
        tmp_path=tmp_path,
    )

    assert summary.result.kind == "correct"
    assert summary.result.turns == 2
    assert summary.turns == 2
    assert summary.framework == "autogen"


@pytest.mark.usefixtures("_patch_prompts")
async def test_timeout(tmp_path: Path) -> None:
    """Guesser never guesses correctly and hits the turn limit."""
    completions: list[CreateResult] = []
    for i in range(1, 21):
        completions.append(_text_reply(f"Question {i}?"))
        completions.append(_answer_reply("no"))

    summary = await _run_with_replay(completions=completions, tmp_path=tmp_path)

    assert summary.result.kind == "timeout"
    assert summary.result.limit == 20
    assert summary.turns == 20


@pytest.mark.usefixtures("_patch_prompts")
async def test_correct_on_first_turn(tmp_path: Path) -> None:
    """Guesser guesses correctly immediately on turn 1."""
    summary = await _run_with_replay(
        completions=[_text_reply("My answer is: New Mexico"), _correct_reply()], tmp_path=tmp_path
    )

    assert summary.result.kind == "correct"
    assert summary.result.turns == 1
    assert summary.turns == 1


@pytest.mark.usefixtures("_patch_prompts")
async def test_sort_of_response(tmp_path: Path) -> None:
    """Simulator responds with sort_of, game continues."""
    summary = await _run_with_replay(
        completions=[
            _text_reply("Is it hot?"),
            _answer_reply("sort_of"),
            _text_reply("My answer is: New Mexico"),
            _correct_reply(),
        ],
        tmp_path=tmp_path,
    )

    assert summary.result.kind == "correct"
    assert summary.result.turns == 2


@pytest.mark.usefixtures("_patch_prompts")
async def test_log_files_written(tmp_path: Path) -> None:
    """JSONL and summary files are written with correct content."""
    await _run_with_replay(completions=[_text_reply("My answer is: New Mexico"), _correct_reply()], tmp_path=tmp_path)

    jsonl_files = list(tmp_path.glob("*_calls.jsonl"))
    summary_files = list(tmp_path.glob("*_summary.json"))
    assert len(jsonl_files) == 1
    assert len(summary_files) == 1

    # JSONL has at least one guesser + one simulator entry.
    lines = jsonl_files[0].read_text().strip().split("\n")
    assert len(lines) >= 2

    summary_data = json.loads(summary_files[0].read_text())
    assert summary_data["framework"] == "autogen"
    assert summary_data["result"]["kind"] == "correct"


if __name__ == "__main__":
    pytest_bazel.main()
