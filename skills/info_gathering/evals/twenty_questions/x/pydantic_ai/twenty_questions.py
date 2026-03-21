"""Twenty Questions eval using PydanticAI."""

import argparse
import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage
from pydantic_ai.toolsets import AbstractToolset
from pydantic_ai.toolsets.fastmcp import FastMCPToolset

from mcp_infra.exec.docker.server import ContainerExecServer
from skills.info_gathering.evals.twenty_questions.prompts import (
    build_guesser_system,
    first_user_message,
    load_sim_prompt,
    load_skill_prompt,
)
from skills.info_gathering.evals.twenty_questions.result_types import Correct, LogEntry, Result, RunSummary, Timeout
from skills.info_gathering.evals.twenty_questions.x.shared.cli import (
    add_common_args,
    output_dir_from_args,
    resolve_args,
)
from skills.info_gathering.evals.twenty_questions.x.shared.docker_exec import scratch_exec_server
from skills.info_gathering.evals.twenty_questions.x.shared.output import run_output_paths, save_summary
from skills.info_gathering.evals.twenty_questions.x.shared.variants import VARIANTS

logger = logging.getLogger(__name__)


# -- Simulator output types --
# The simulator agent uses output_type to force structured responses via tool
# calling. PydanticAI registers each union member as a separate "output tool",
# so the model MUST return one of these -- no free-text responses are possible.


class SimAnswer(BaseModel):
    """The simulator answers a yes/no question."""

    response: Literal["yes", "no", "sort_of"]


class SimCorrectAnswer(BaseModel):
    """The simulator confirms the guesser's answer is correct."""


SimAction = SimAnswer | SimCorrectAnswer


# -- Agent construction --
# Agents are module-level singletons (PydanticAI best practice). The model is
# set to None here and overridden at runtime via agent.run(model=...) or
# agent.override(model=...) in tests.

guesser_agent: Agent[None, str] = Agent(
    # Model is set at runtime via run(model=...) or override(model=...) in tests.
    # defer_model_check is needed so run(model=None) doesn't fail when override() is active.
    defer_model_check=True
)

sim_agent: Agent[None, SimAction] = Agent(
    defer_model_check=True,
    # output_type forces the model to call one of two output tools:
    # `final_result_SimAnswer` or `final_result_SimCorrectAnswer`.
    # No free-text fallback is possible since str is not in the union.
    output_type=[SimAnswer, SimCorrectAnswer],
)


def _make_model_id(api: str, model: str) -> str:
    if api == "openai":
        return f"openai:{model}"
    return f"anthropic:{model}"


async def run_game_loop(
    *,
    model_id: str | None,
    guesser_instructions: str,
    sim_instructions: str,
    opening: str,
    turn_limit: int,
    guesser_toolsets: list[AbstractToolset[None]] | None = None,
) -> tuple[Result, int, list[LogEntry]]:
    """Run the game loop, returning (result, turns_played, log_entries)."""
    log_entries: list[LogEntry] = []

    def record(
        player: Literal["guesser", "simulator"], content: str, tool_calls: list[dict[str, object]] | None = None
    ) -> None:
        log_entries.append(
            LogEntry(timestamp=datetime.now(UTC), player=player, content=content, tool_calls=tool_calls or [])
        )

    # Both agents carry their full conversation history across turns.
    # On the first turn message_history is None, so PydanticAI generates
    # a fresh system prompt from `instructions`. On subsequent turns the
    # history is passed and instructions are re-injected automatically.
    guesser_history: list[ModelMessage] | None = None
    guesser_input: str = opening
    sim_history: list[ModelMessage] | None = None

    result: Result = Timeout(limit=turn_limit)
    turn = 0

    for turn in range(1, turn_limit + 1):
        logger.info("Turn %d...", turn)

        # -- Guesser turn: produce a text question --
        # PydanticAI handles tool calls (e.g. exec) as internal round-trips
        # within a single run() invocation.
        guesser_run = await guesser_agent.run(
            guesser_input,
            model=model_id,
            message_history=guesser_history,
            instructions=guesser_instructions,
            toolsets=guesser_toolsets or [],
        )
        guesser_history = guesser_run.all_messages()
        question = guesser_run.output.strip()
        record("guesser", question)
        logger.info("Guesser: %s", question[:200])

        if not question:
            logger.warning("Guesser produced empty text, ending game")
            break

        # -- Simulator turn: forced structured output via output_type --
        sim_run = await sim_agent.run(
            question, model=model_id, message_history=sim_history, instructions=sim_instructions
        )
        sim_history = sim_run.all_messages()
        action: SimAction = sim_run.output

        # Log the structured action.
        if isinstance(action, SimAnswer):
            record("simulator", action.response, [{"name": "answer", "args": {"response": action.response}}])
        else:
            record("simulator", "", [{"name": "correct_answer", "args": {}}])

        if isinstance(action, SimCorrectAnswer):
            result = Correct(turns=turn)
            logger.info("Correct answer on turn %d!", turn)
            break

        # Feed the simulator's answer back to the guesser as the next prompt.
        guesser_input = action.response
        logger.info("Simulator answered: %s", action.response)

    return result, turn, log_entries


async def run_twenty_questions(
    *,
    name: str,
    model_id: str,
    model_name: str,
    api: str,
    variant_name: str,
    output_dir: Path,
    exec_server: ContainerExecServer | None = None,
) -> RunSummary:
    variant = VARIANTS[variant_name]
    calls_path, summary_path = run_output_paths(name, output_dir)

    sim_instructions = load_sim_prompt(secret=variant.secret, turn_limit=variant.turn_limit)
    skill_text = load_skill_prompt()
    guesser_instructions = build_guesser_system(skill_text)
    opening = first_user_message(variant.domain_description, variant.turn_limit)

    guesser_toolsets: list[AbstractToolset[None]] | None = None
    if exec_server is not None:
        guesser_toolsets = [FastMCPToolset(exec_server)]

    result, turn, log_entries = await run_game_loop(
        model_id=model_id,
        guesser_instructions=guesser_instructions,
        sim_instructions=sim_instructions,
        opening=opening,
        turn_limit=variant.turn_limit,
        guesser_toolsets=guesser_toolsets,
    )

    with calls_path.open("w") as f:
        for entry in log_entries:
            f.write(entry.model_dump_json() + "\n")

    summary = RunSummary(eval_name=name, framework="pydantic_ai", model=model_name, api=api, turns=turn, result=result)
    save_summary(summary=summary, summary_path=summary_path)
    return summary


async def _async_main(args: argparse.Namespace) -> None:
    name = f"20q_{args.variant}"
    output_dir = output_dir_from_args(args)
    model_id = _make_model_id(args.api, args.model)

    logger.info("=" * 60)
    logger.info("  %s  |  %s  |  %s (pydantic_ai)", name, args.model, args.api)
    logger.info("=" * 60)

    async with scratch_exec_server() as exec_server:
        summary = await run_twenty_questions(
            name=name,
            model_id=model_id,
            model_name=args.model,
            api=args.api,
            variant_name=args.variant,
            output_dir=output_dir,
            exec_server=exec_server,
        )
    logger.info("%s", summary)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    p = argparse.ArgumentParser(description="Twenty Questions eval (PydanticAI)")
    add_common_args(p)
    args = p.parse_args()
    resolve_args(args)

    asyncio.run(_async_main(args))


if __name__ == "__main__":
    main()
