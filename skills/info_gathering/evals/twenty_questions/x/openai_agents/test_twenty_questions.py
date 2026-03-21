"""Tests for Twenty Questions OpenAI Agents SDK implementation.

Mocks ``Runner.run`` and the prompt loaders. Tool results are communicated
via ``RunResult.new_items`` containing ``ToolCallOutputItem`` instances.
"""

from contextlib import contextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest_bazel
from agents import ToolCallOutputItem

from skills.info_gathering.evals.twenty_questions.result_types import Correct, Timeout
from skills.info_gathering.evals.twenty_questions.x.openai_agents.twenty_questions import run_twenty_questions

_MODULE = "skills.info_gathering.evals.twenty_questions.x.openai_agents.twenty_questions"


def _make_tool_output_item(output: str) -> ToolCallOutputItem:
    """Build a ToolCallOutputItem with the given tool return value."""
    return ToolCallOutputItem(agent=MagicMock(), raw_item={"output": output}, output=output)


def _make_run_result(*, final_output: str, tool_outputs: list[ToolCallOutputItem] | None = None) -> MagicMock:
    """Build a mock RunResult with the fields the game loop reads."""
    result = MagicMock()
    result.final_output = final_output
    result.new_items = tool_outputs or []
    result.to_input_list.return_value = [{"role": "assistant", "content": final_output}]
    return result


@contextmanager
def _patched_game():
    """Patch SDK classes and prompt loaders.

    Yields ``mock_runner_cls`` for configuring ``Runner.run`` behavior.
    """
    with (
        patch(f"{_MODULE}.Agent") as mock_agent_cls,
        patch(f"{_MODULE}.Runner") as mock_runner_cls,
        patch(f"{_MODULE}.load_sim_prompt", return_value="sim prompt"),
        patch(f"{_MODULE}.load_skill_prompt", return_value="skill"),
        patch(f"{_MODULE}.build_guesser_system", return_value="guesser sys"),
    ):
        guesser_agent = MagicMock()
        guesser_agent.name = "guesser"
        simulator_agent = MagicMock()
        simulator_agent.name = "simulator"

        def agent_factory(*, name: str, **kw: Any) -> MagicMock:
            if name == "simulator":
                return simulator_agent
            return guesser_agent

        mock_agent_cls.side_effect = agent_factory
        yield mock_runner_cls


async def test_correct_answer_first_turn(tmp_path: Any) -> None:
    """Simulator calls correct_answer on turn 1."""
    with _patched_game() as mock_runner_cls:

        async def runner_run(agent: Any, input: Any, **kwargs: Any) -> MagicMock:
            if agent.name == "guesser":
                return _make_run_result(final_output="Is it New Mexico?")
            return _make_run_result(final_output="", tool_outputs=[_make_tool_output_item("Correct!")])

        mock_runner_cls.run = AsyncMock(side_effect=runner_run)

        summary = await run_twenty_questions(
            name="test_correct", model="gpt-4o-mini", variant_name="states", api="openai", output_dir=tmp_path
        )

    assert isinstance(summary.result, Correct)
    assert summary.result.turns == 1
    assert summary.turns == 1
    assert summary.framework == "openai_agents"


async def test_correct_answer_mid_game(tmp_path: Any) -> None:
    """Simulator answers 'no' twice then calls correct_answer on turn 3."""
    with _patched_game() as mock_runner_cls:
        turn_counter = 0

        async def runner_run(agent: Any, input: Any, **kwargs: Any) -> MagicMock:
            nonlocal turn_counter
            if agent.name == "guesser":
                turn_counter += 1
                return _make_run_result(final_output=f"Question #{turn_counter}")
            if turn_counter == 3:
                return _make_run_result(final_output="", tool_outputs=[_make_tool_output_item("Correct!")])
            return _make_run_result(final_output="", tool_outputs=[_make_tool_output_item("Answered: no")])

        mock_runner_cls.run = AsyncMock(side_effect=runner_run)

        summary = await run_twenty_questions(
            name="test_mid", model="gpt-4o-mini", variant_name="states", api="openai", output_dir=tmp_path
        )

    assert isinstance(summary.result, Correct)
    assert summary.result.turns == 3
    assert summary.turns == 3


async def test_simulator_receives_history_on_later_turns(tmp_path: Any) -> None:
    """After turn 1 the simulator receives a list (history), not a string."""
    with _patched_game() as mock_runner_cls:
        turn_counter = 0
        sim_inputs: list[object] = []

        async def runner_run(agent: Any, input: Any, **kwargs: Any) -> MagicMock:
            nonlocal turn_counter
            if agent.name == "guesser":
                turn_counter += 1
                return _make_run_result(final_output=f"Q{turn_counter}")
            sim_inputs.append(input)
            if turn_counter == 2:
                return _make_run_result(final_output="", tool_outputs=[_make_tool_output_item("Correct!")])
            return _make_run_result(final_output="", tool_outputs=[_make_tool_output_item("Answered: no")])

        mock_runner_cls.run = AsyncMock(side_effect=runner_run)

        await run_twenty_questions(
            name="test_history", model="gpt-4o-mini", variant_name="states", api="openai", output_dir=tmp_path
        )

    # Both turns: simulator receives a list (conversation history).
    assert isinstance(sim_inputs[0], list)
    assert isinstance(sim_inputs[1], list)
    # Turn 2 has more history than turn 1.
    assert len(sim_inputs[1]) > len(sim_inputs[0])


async def test_timeout(tmp_path: Any) -> None:
    """Game runs to turn limit without a correct answer."""
    with _patched_game() as mock_runner_cls:
        turn_counter = 0

        async def runner_run(agent: Any, input: Any, **kwargs: Any) -> MagicMock:
            nonlocal turn_counter
            if agent.name == "guesser":
                turn_counter += 1
                return _make_run_result(final_output=f"Is it state #{turn_counter}?")
            return _make_run_result(final_output="", tool_outputs=[_make_tool_output_item("Answered: no")])

        mock_runner_cls.run = AsyncMock(side_effect=runner_run)

        summary = await run_twenty_questions(
            name="test_timeout", model="gpt-4o-mini", variant_name="states", api="openai", output_dir=tmp_path
        )

    assert isinstance(summary.result, Timeout)
    assert summary.result.limit == 20
    assert summary.turns == 20


async def test_output_files_written(tmp_path: Any) -> None:
    """Both JSONL log and JSON summary files are created."""
    with _patched_game() as mock_runner_cls:

        async def runner_run(agent: Any, input: Any, **kwargs: Any) -> MagicMock:
            if agent.name == "guesser":
                return _make_run_result(final_output="Is it New Mexico?")
            return _make_run_result(final_output="", tool_outputs=[_make_tool_output_item("Correct!")])

        mock_runner_cls.run = AsyncMock(side_effect=runner_run)

        await run_twenty_questions(
            name="test_output", model="gpt-4o-mini", variant_name="states", api="openai", output_dir=tmp_path
        )

    files = list(tmp_path.iterdir())
    jsonl_files = [f for f in files if f.suffix == ".jsonl"]
    json_files = [f for f in files if f.name.endswith("_summary.json")]
    assert len(jsonl_files) == 1, f"Expected 1 JSONL file, got {jsonl_files}"
    assert len(json_files) == 1, f"Expected 1 summary JSON file, got {json_files}"
    # JSONL should have at least a guesser and simulator entry.
    lines = jsonl_files[0].read_text().strip().splitlines()
    assert len(lines) >= 2


async def test_summary_fields(tmp_path: Any) -> None:
    """RunSummary has correct framework and api fields."""
    with _patched_game() as mock_runner_cls:

        async def runner_run(agent: Any, input: Any, **kwargs: Any) -> MagicMock:
            if agent.name == "guesser":
                return _make_run_result(final_output="My answer is: New Mexico")
            return _make_run_result(final_output="", tool_outputs=[_make_tool_output_item("Correct!")])

        mock_runner_cls.run = AsyncMock(side_effect=runner_run)

        summary = await run_twenty_questions(
            name="test_fields", model="gpt-4o-mini", variant_name="states", api="openai", output_dir=tmp_path
        )

    assert summary.eval_name == "test_fields"
    assert summary.framework == "openai_agents"
    assert summary.model == "gpt-4o-mini"
    assert summary.api == "openai"


async def test_sort_of_response(tmp_path: Any) -> None:
    """Simulator can answer 'sort_of' and the game continues."""
    with _patched_game() as mock_runner_cls:
        turn_counter = 0

        async def runner_run(agent: Any, input: Any, **kwargs: Any) -> MagicMock:
            nonlocal turn_counter
            if agent.name == "guesser":
                turn_counter += 1
                return _make_run_result(final_output=f"Question {turn_counter}")
            if turn_counter == 1:
                return _make_run_result(final_output="", tool_outputs=[_make_tool_output_item("Answered: sort_of")])
            return _make_run_result(final_output="", tool_outputs=[_make_tool_output_item("Correct!")])

        mock_runner_cls.run = AsyncMock(side_effect=runner_run)

        summary = await run_twenty_questions(
            name="test_sort_of", model="gpt-4o-mini", variant_name="states", api="openai", output_dir=tmp_path
        )

    assert isinstance(summary.result, Correct)
    assert summary.result.turns == 2


if __name__ == "__main__":
    pytest_bazel.main()
