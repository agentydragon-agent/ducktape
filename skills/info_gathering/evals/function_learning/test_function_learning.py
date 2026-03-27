"""Tests for the function learning game loop.

Uses ReplayChatCompletionClient for scripted LLM responses, but runs real
Docker-based program evaluation (no mocking of evaluate_program).
"""

import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import aiodocker
import pytest
import pytest_bazel
from autogen_core import FunctionCall
from autogen_core.models import CreateResult, RequestUsage
from autogen_ext.models.replay import ReplayChatCompletionClient

from skills.info_gathering.evals.function_learning.function_learning import run_game
from skills.info_gathering.evals.function_learning.functions import PARITY_GROUPS
from skills.info_gathering.evals.function_learning.result_types import RunSummary

_ZERO_USAGE = RequestUsage(prompt_tokens=0, completion_tokens=0)
_TEST_TURNS = 3


def _play_turn_call(query: int, program: str) -> CreateResult:
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

    # Real Docker-based scoring — no mocking of evaluate_program.
    async with aiodocker.Docker() as docker:
        container = await docker.containers.run(
            config={"Image": "python:3.13-slim", "Cmd": ["sleep", "300"]}, name=f"fl-test-{uuid.uuid4().hex[:8]}"
        )
        try:
            return await run_game(
                variant_name=variant_name,
                model="test-model",
                api="openai",
                output_dir=tmp_path,
                model_client=client,
                scoring_container=container,
                turn_limit=turn_limit,
            )
        finally:
            await container.stop()
            await container.delete(force=True)


@pytest.mark.usefixtures("_patch_prompts")
async def test_basic_game_completes(tmp_path: Path) -> None:
    """Model plays 3 turns with a trivial all-zeros program, game completes."""
    completions = [_play_turn_call(i, "x = int(input()); print(0)") for i in range(_TEST_TURNS)]

    summary = await _run_with_replay(completions=completions, tmp_path=tmp_path)

    assert summary.result.kind == "completed"
    assert len(summary.result.per_turn_losses) == _TEST_TURNS
    assert summary.turns == _TEST_TURNS
    # All-zeros program should have non-zero loss (parity_groups isn't all zeros).
    assert summary.result.total_hamming_loss > 0


@pytest.mark.usefixtures("_patch_prompts")
async def test_perfect_program_zero_loss(tmp_path: Path) -> None:
    """A program implementing the correct parity function gets 0 loss."""
    # Reads decimal, extracts bits, computes XOR of pairs, prints decimal result.
    perfect_program = (
        "x = int(input()); bits = [(x >> (7 - i)) & 1 for i in range(8)]; "
        "r = sum((bits[i] ^ bits[i+1]) << (3 - i//2) for i in range(0, 8, 2)); print(r)"
    )
    completions = [_play_turn_call(i, perfect_program) for i in range(_TEST_TURNS)]

    summary = await _run_with_replay(completions=completions, tmp_path=tmp_path)

    assert summary.result.total_hamming_loss == 0
    assert all(loss == 0 for loss in summary.result.per_turn_losses)


@pytest.mark.usefixtures("_patch_prompts")
async def test_improving_programs(tmp_path: Path) -> None:
    """Loss should decrease as the program improves turn over turn."""
    programs = [
        # Turn 1: always output 0 (bad)
        "x = int(input()); print(0)",
        # Turn 2: gets first pair right, rest zeros
        "x = int(input()); b0 = (x >> 7) & 1; b1 = (x >> 6) & 1; print((b0 ^ b1) << 3)",
        # Turn 3: gets all pairs right (perfect)
        (
            "x = int(input()); bits = [(x >> (7 - i)) & 1 for i in range(8)]; "
            "r = sum((bits[i] ^ bits[i+1]) << (3 - i//2) for i in range(0, 8, 2)); print(r)"
        ),
    ]
    completions = [_play_turn_call(i, programs[i]) for i in range(_TEST_TURNS)]

    summary = await _run_with_replay(completions=completions, tmp_path=tmp_path)

    losses = summary.result.per_turn_losses
    assert len(losses) == 3
    assert losses[0] > losses[1] > losses[2]
    assert losses[2] == 0


@pytest.mark.usefixtures("_patch_prompts")
async def test_erroring_program_max_loss(tmp_path: Path) -> None:
    """A program that raises an exception gets maximum loss per errored input."""
    completions = [_play_turn_call(0, "raise ValueError('broken')")]

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
    completions = [_play_turn_call(0, "x = int(input()); print(0)") for _ in range(_TEST_TURNS)]
    await _run_with_replay(completions=completions, tmp_path=tmp_path)
    _check_output_files(tmp_path)


if __name__ == "__main__":
    pytest_bazel.main()
