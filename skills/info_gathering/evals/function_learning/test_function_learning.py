"""Tests for the function learning game loop.

Uses ReplayChatCompletionClient for scripted LLM responses, but runs real
Docker-based program evaluation (no mocking of evaluate_program).
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import pytest_bazel
from autogen_core import FunctionCall
from autogen_core.models import CreateResult, RequestUsage
from autogen_ext.models.replay import ReplayChatCompletionClient
from fastmcp.client import Client

from skills.info_gathering.evals.docker_exec import scratch_exec_server
from skills.info_gathering.evals.function_learning.function_learning import run_game
from skills.info_gathering.evals.function_learning.functions import PARITY_GROUPS
from skills.info_gathering.evals.function_learning.result_types import RunSummary

_ZERO_USAGE = RequestUsage(prompt_tokens=0, completion_tokens=0)
_TEST_TURNS = 3


def _play_turn_call(query: str, program: str) -> CreateResult:
    return CreateResult(
        finish_reason="function_calls",
        content=[
            FunctionCall(id="call_1", name="play_turn", arguments=json.dumps({"query": query, "program": program}))
        ],
        usage=_ZERO_USAGE,
        cached=False,
    )


@pytest.fixture
def _patch_prompts(monkeypatch):
    monkeypatch.setattr(
        "skills.info_gathering.evals.function_learning.function_learning.load_skill_prompt",
        MagicMock(return_value="You are skilled."),
    )
    monkeypatch.setattr(
        "skills.info_gathering.evals.function_learning.prompts.load_scratch_system_note",
        MagicMock(return_value="You have a scratch container."),
    )


async def _run_with_replay(
    *,
    completions: list[CreateResult],
    tmp_path: Path,
    variant_name: str = "parity_groups",
    turn_limit: int = _TEST_TURNS,
) -> RunSummary:
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

    # Real Docker-based scoring — no mocking.
    async with scratch_exec_server() as scoring_server, Client(scoring_server) as scoring_client:
        return await run_game(
            variant_name=variant_name,
            model="test-model",
            api="openai",
            output_dir=tmp_path,
            model_client=client,
            scoring_client=scoring_client,
            turn_limit=turn_limit,
        )


@pytest.mark.usefixtures("_patch_prompts")
async def test_basic_game_completes(tmp_path: Path) -> None:
    """Model plays 3 turns with a trivial all-zeros program, game completes."""
    completions = [_play_turn_call(f"{i:08b}", "x = input(); print('0000')") for i in range(_TEST_TURNS)]

    summary = await _run_with_replay(completions=completions, tmp_path=tmp_path)

    assert summary.result.kind == "completed"
    assert len(summary.result.per_turn_losses) == _TEST_TURNS
    assert summary.turns == _TEST_TURNS
    # All-zeros program should have non-zero loss (parity_groups isn't all zeros).
    assert summary.result.total_hamming_loss > 0


@pytest.mark.usefixtures("_patch_prompts")
async def test_perfect_program_zero_loss(tmp_path: Path) -> None:
    """A program implementing the correct parity function gets 0 loss."""
    # This program correctly computes XOR of pairs (0,1), (2,3), (4,5), (6,7).
    perfect_program = "x = input(); print(''.join(str(int(x[i]) ^ int(x[i+1])) for i in range(0, 8, 2)))"
    completions = [_play_turn_call(f"{i:08b}", perfect_program) for i in range(_TEST_TURNS)]

    summary = await _run_with_replay(completions=completions, tmp_path=tmp_path)

    assert summary.result.total_hamming_loss == 0
    assert all(loss == 0 for loss in summary.result.per_turn_losses)


@pytest.mark.usefixtures("_patch_prompts")
async def test_improving_programs(tmp_path: Path) -> None:
    """Loss should decrease as the program improves turn over turn."""
    # Turn 1: all zeros (bad)
    # Turn 2: gets first pair right
    # Turn 3: gets all pairs right (perfect)
    programs = [
        "x = input(); print('0000')",
        "x = input(); print(str(int(x[0]) ^ int(x[1])) + '000')",
        "x = input(); print(''.join(str(int(x[i]) ^ int(x[i+1])) for i in range(0, 8, 2)))",
    ]
    completions = [_play_turn_call(f"{i:08b}", programs[i]) for i in range(_TEST_TURNS)]

    summary = await _run_with_replay(completions=completions, tmp_path=tmp_path)

    losses = summary.result.per_turn_losses
    assert len(losses) == 3
    assert losses[0] > losses[1] > losses[2]
    assert losses[2] == 0  # Perfect on turn 3.


@pytest.mark.usefixtures("_patch_prompts")
async def test_erroring_program_max_loss(tmp_path: Path) -> None:
    """A program that raises an exception gets maximum loss per errored input."""
    completions = [_play_turn_call("00000000", "raise ValueError('broken')")]

    summary = await _run_with_replay(completions=completions, tmp_path=tmp_path, turn_limit=1)

    # Every input errors: max loss = 256 inputs x 4 bits = 1024.
    assert summary.result.per_turn_losses[0] == 256 * PARITY_GROUPS.m


def _check_output_files(tmp_path: Path) -> None:
    """Verify JSONL and summary files exist with correct structure (sync helper)."""
    jsonl_files = list(tmp_path.glob("*_calls.jsonl"))
    summary_files = list(tmp_path.glob("*_summary.json"))
    assert len(jsonl_files) == 1
    assert len(summary_files) == 1

    summary_data = json.loads(summary_files[0].read_text())
    assert summary_data["framework"] == "autogen"
    assert summary_data["result"]["kind"] == "completed"


@pytest.mark.usefixtures("_patch_prompts")
async def test_output_files_written(tmp_path: Path) -> None:
    completions = [_play_turn_call("00000000", "x = input(); print('0000')") for _ in range(_TEST_TURNS)]
    await _run_with_replay(completions=completions, tmp_path=tmp_path)
    _check_output_files(tmp_path)


if __name__ == "__main__":
    pytest_bazel.main()
