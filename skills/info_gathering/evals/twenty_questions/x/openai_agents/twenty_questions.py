"""Twenty Questions eval using the OpenAI Agents SDK.

Two agents play a game: a *guesser* asks yes/no questions and the *simulator*
answers via tool calls (``answer`` / ``correct_answer``).  Conversation history
is threaded through ``RunResult.to_input_list()`` between turns.
"""

import argparse
import asyncio
import logging
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from agents import (
    Agent,
    FunctionTool,
    ModelSettings,
    Runner,
    Tool,
    ToolCallOutputItem,
    TResponseInputItem,
    function_tool,
)
from fastmcp.client import Client
from mcp.types import TextContent

from mcp_infra.exec.docker.server import ContainerExecServer
from skills.info_gathering.evals.twenty_questions.prompts import (
    build_guesser_system,
    first_user_message,
    load_sim_prompt,
    load_skill_prompt,
)
from skills.info_gathering.evals.twenty_questions.result_types import Correct, LogEntry, RunSummary, Timeout
from skills.info_gathering.evals.twenty_questions.x.shared.cli import (
    add_common_args,
    output_dir_from_args,
    resolve_args,
)
from skills.info_gathering.evals.twenty_questions.x.shared.docker_exec import scratch_exec_server
from skills.info_gathering.evals.twenty_questions.x.shared.output import run_output_paths, save_summary
from skills.info_gathering.evals.twenty_questions.x.shared.variants import VARIANTS

logger = logging.getLogger(__name__)

# Allow multiple exec tool calls per question before the guesser produces text.
_GUESSER_MAX_TOOL_ROUNDS = 25
# One tool call (answer/correct_answer) + tool result.
_SIMULATOR_MAX_TURNS = 2


def _make_exec_tool(mcp_client: Client) -> FunctionTool:
    """Create a @function_tool that proxies to the MCP exec tool via fastmcp.Client."""

    @function_tool(name_override="exec")
    async def run_exec(cmd: list[str], cwd: str | None = None, timeout_ms: int = 30000) -> str:
        """Run a command in a scratch Docker container."""
        result = await mcp_client.call_tool("exec", {"cmd": cmd, "cwd": cwd, "timeout_ms": timeout_ms})
        return "\n".join(block.text for block in result.content if isinstance(block, TextContent))

    return run_exec


async def run_twenty_questions(
    *,
    name: str,
    model: str,
    variant_name: str,
    api: str,
    output_dir: Path,
    exec_server: ContainerExecServer | None = None,
) -> RunSummary:
    """Run a full 20 Questions game using the OpenAI Agents SDK."""
    variant = VARIANTS[variant_name]
    calls_path, summary_path = run_output_paths(name, output_dir)

    sim_system = load_sim_prompt(secret=variant.secret, turn_limit=variant.turn_limit)
    skill_text = load_skill_prompt()
    guesser_system = build_guesser_system(skill_text)
    opening = first_user_message(variant.domain_description, variant.turn_limit)

    @function_tool
    def answer(response: Literal["yes", "no", "sort_of"]) -> str:
        """Answer the player's yes/no question."""
        return f"Answered: {response}"

    @function_tool
    def correct_answer() -> str:
        """The player correctly guessed the secret."""
        return "Correct!"

    guesser_tools: list[Tool] = []
    async with AsyncExitStack() as stack:
        if exec_server is not None:
            mcp_client = await stack.enter_async_context(Client(exec_server))
            guesser_tools.append(_make_exec_tool(mcp_client))

        guesser_agent = Agent(name="guesser", instructions=guesser_system, model=model, tools=guesser_tools)

        simulator_agent = Agent(
            name="simulator",
            instructions=sim_system,
            model=model,
            tools=[answer, correct_answer],
            model_settings=ModelSettings(tool_choice="required"),
        )

        log_entries: list[LogEntry] = []

        def record_entry(
            player: Literal["guesser", "simulator"], content: str, tool_calls: list[dict[str, object]] | None = None
        ) -> None:
            log_entries.append(
                LogEntry(timestamp=datetime.now(UTC), player=player, content=content, tool_calls=tool_calls or [])
            )

        # Both agents accumulate conversation history via to_input_list().
        guesser_input: str | list[TResponseInputItem] = opening
        sim_input: list[TResponseInputItem] = []
        result: Correct | Timeout = Timeout(limit=variant.turn_limit)
        turn = 0

        for turn in range(1, variant.turn_limit + 1):
            logger.info("Turn %d...", turn)

            # -- Guesser turn --
            guesser_result = await Runner.run(guesser_agent, input=guesser_input, max_turns=_GUESSER_MAX_TOOL_ROUNDS)
            guesser_text = str(guesser_result.final_output or "")
            record_entry("guesser", guesser_text)
            logger.info("Guesser: %s", guesser_text[:200])

            if not guesser_text.strip():
                logger.warning("Guesser produced empty text, ending game")
                break

            # -- Simulator turn --
            sim_result = await Runner.run(
                simulator_agent,
                input=[*sim_input, {"role": "user", "content": guesser_text}],
                max_turns=_SIMULATOR_MAX_TURNS,
            )

            # Extract tool results from new_items via ToolCallOutputItem.
            tool_call_dicts: list[dict[str, object]] = []
            sim_response: str | None = None
            is_correct = False
            for item in sim_result.new_items:
                if isinstance(item, ToolCallOutputItem):
                    output = str(item.output)
                    tool_call_dicts.append({"output": output})
                    if output == "Correct!":
                        is_correct = True
                    elif output.startswith("Answered: "):
                        sim_response = output.removeprefix("Answered: ")

            sim_text = str(sim_result.final_output or "")
            record_entry("simulator", sim_text, tool_call_dicts)

            if is_correct:
                result = Correct(turns=turn)
                logger.info("Correct answer on turn %d!", turn)
                break

            if sim_response is not None:
                # Feed the simulator's answer back to the guesser for the next turn.
                guesser_input = [*guesser_result.to_input_list(), {"role": "user", "content": sim_response}]
                # Preserve simulator conversation history for the next turn.
                sim_input = sim_result.to_input_list()
                logger.info("Simulator answered: %s", sim_response)
            else:
                logger.warning("Simulator did not produce an expected tool call, ending")
                break

    # Write JSONL log.
    with calls_path.open("w") as f:
        for entry in log_entries:
            f.write(entry.model_dump_json() + "\n")

    summary = RunSummary(eval_name=name, framework="openai_agents", model=model, api=api, turns=turn, result=result)
    save_summary(summary=summary, summary_path=summary_path)
    return summary


async def _async_main(args: argparse.Namespace) -> None:
    name = f"20q_{args.variant}"
    output_dir = output_dir_from_args(args)

    logger.info("=" * 60)
    logger.info("  %s  |  %s  |  openai_agents", name, args.model)
    logger.info("=" * 60)

    async with scratch_exec_server() as server:
        summary = await run_twenty_questions(
            name=name,
            model=args.model,
            variant_name=args.variant,
            api=args.api,
            output_dir=output_dir,
            exec_server=server,
        )
    logger.info("%s", summary)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    p = argparse.ArgumentParser(description="Twenty Questions (OpenAI Agents SDK)")
    add_common_args(p)
    args = p.parse_args()
    resolve_args(args)

    asyncio.run(_async_main(args))


if __name__ == "__main__":
    main()
