"""Twenty Questions game using Microsoft Agent Framework with structured guesser tools.

The guesser has tool_choice=required and three tools: ask_yes_no_question,
guess_answer, and exec (scratch computation). Game tools internally invoke the
simulator (a single LLM call with answer/correct_answer/invalid_input tools)
and return the result. No pub/sub messaging — just a direct tool loop.
"""

import argparse
import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from agent_framework import ChatResponse, Content, FunctionTool, Message
from agent_framework.anthropic import AnthropicClient
from agent_framework.openai import OpenAIChatCompletionClient
from fastmcp.client import Client
from mcp.types import TextContent

from skills.info_gathering.evals.docker_exec import scratch_exec_server
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
from skills.info_gathering.evals.twenty_questions.x.shared.output import run_output_paths, save_summary
from skills.info_gathering.evals.twenty_questions.x.shared.variants import VARIANTS

logger = logging.getLogger(__name__)


# -- Shared game state --


@dataclass
class GameContext:
    """Mutable game state. Shared via closures (single-threaded)."""

    turn_limit: int
    turn: int = 0
    result: Result | None = None
    invalid_input_count: int = 0
    log_entries: list[LogEntry] = field(default_factory=list)

    def record(
        self, player: Literal["guesser", "simulator"], content: str, tool_calls: list[dict[str, object]] | None = None
    ) -> None:
        self.log_entries.append(
            LogEntry(timestamp=datetime.now(UTC), player=player, content=content, tool_calls=tool_calls or [])
        )


# -- Simulator: a stateful function, not an agent --


def _make_sim_tools(game: GameContext) -> list[FunctionTool]:
    """Create simulator tools that capture game state via closure."""

    async def answer(response: Literal["yes", "no", "sort_of"]) -> str:
        """Answer the player's yes/no question."""
        game.record("simulator", response, [{"name": "answer", "args": {"response": response}}])
        logger.info("Simulator: %s", response)
        return response

    async def correct_answer() -> str:
        """The player correctly guessed the secret."""
        game.result = Correct(turns=game.turn)
        game.record("simulator", "", [{"name": "correct_answer", "args": {}}])
        logger.info("Correct answer on turn %d!", game.turn)
        return "correct"

    async def invalid_input(reason: str) -> str:
        """The player's input is not a valid yes/no question or guess."""
        game.invalid_input_count += 1
        game.record("simulator", reason, [{"name": "invalid_input", "args": {"reason": reason}}])
        logger.info("Simulator: invalid_input — %s", reason)
        return reason

    return [
        FunctionTool(name="answer", description="Answer a yes/no question.", func=answer),
        FunctionTool(name="correct_answer", description="The player guessed correctly.", func=correct_answer),
        FunctionTool(
            name="invalid_input", description="The input is not a valid question or guess.", func=invalid_input
        ),
    ]


def _extract_function_calls(response: ChatResponse) -> list[Content]:
    """Extract function call Content items from a ChatResponse."""
    msg = response.messages[0]
    return [c for c in msg.contents if c.type == "function_call"]


async def _run_simulator(
    *, model_client: Any, sim_history: list[Message], sim_tools: list[FunctionTool], text: str
) -> str:
    """Run one simulator turn: append text, call LLM with required tool use, execute tool, return result."""
    sim_history.append(Message("user", [text]))
    sim_tool_map = {t.name: t for t in sim_tools}

    response = await model_client.get_response(
        sim_history, options={"tools": sim_tools, "tool_choice": "required", "allow_multiple_tool_calls": False}
    )

    function_calls = _extract_function_calls(response)
    if not function_calls:
        text_content = response.messages[0].text
        raise RuntimeError(f"Simulator returned text instead of tool call: {text_content!r}")

    sim_history.append(response.messages[0])

    results: list[Content] = []
    tool_output = ""
    for fc in function_calls:
        tool = sim_tool_map[fc.name]
        args = json.loads(fc.arguments) if isinstance(fc.arguments, str) else (fc.arguments or {})
        tool_result = await tool.invoke(arguments=args)
        tool_output = tool_result[0].text if tool_result else ""
        results.append(Content.from_function_result(fc.call_id, result=tool_output))
    sim_history.append(Message("tool", results))

    return tool_output


# -- Guesser game tools --


def _make_game_tools(
    *, game: GameContext, model_client: Any, sim_history: list[Message], sim_tools: list[FunctionTool]
) -> list[FunctionTool]:
    """Create guesser game tools that internally invoke the simulator."""

    async def ask_yes_no_question(question: str) -> str:
        """Ask a yes/no question. Uses one turn."""
        game.turn += 1
        game.record("guesser", question, [{"name": "ask_yes_no_question", "args": {"question": question}}])
        logger.info("Guesser (turn %d): %s", game.turn, question[:200])

        sim_response = await _run_simulator(
            model_client=model_client, sim_history=sim_history, sim_tools=sim_tools, text=f"Question: {question}"
        )

        # If simulator returned invalid_input, refund the turn.
        if game.invalid_input_count > 0 and game.log_entries and game.log_entries[-1].tool_calls:
            last_call = game.log_entries[-1].tool_calls[0]
            if last_call.get("name") == "invalid_input":
                game.turn -= 1
                return sim_response

        if game.turn >= game.turn_limit and game.result is None:
            game.result = Timeout(limit=game.turn_limit)

        return sim_response

    async def guess_answer(answer: str) -> str:
        """Guess the secret answer. Uses one turn."""
        game.turn += 1
        game.record("guesser", answer, [{"name": "guess_answer", "args": {"answer": answer}}])
        logger.info("Guesser (turn %d) guesses: %s", game.turn, answer[:200])

        sim_response = await _run_simulator(
            model_client=model_client, sim_history=sim_history, sim_tools=sim_tools, text=f"My answer is: {answer}"
        )

        if game.result is not None:
            return "Correct! You guessed it!"

        if game.turn >= game.turn_limit and game.result is None:
            game.result = Timeout(limit=game.turn_limit)

        return sim_response  # "no" for wrong guess

    return [
        FunctionTool(
            name="ask_yes_no_question", description="Ask a yes/no question. Uses one turn.", func=ask_yes_no_question
        ),
        FunctionTool(name="guess_answer", description="Guess the secret answer. Uses one turn.", func=guess_answer),
    ]


# -- MCP exec tool bridge --


def _make_exec_tool(mcp_client: Client) -> FunctionTool:
    """Create a FunctionTool that delegates to the MCP exec tool via fastmcp.Client."""

    async def exec(cmd: list[str], timeout_ms: int = 30000) -> str:
        """Run a command in a scratch container. cmd is a list of strings (no shell)."""
        arguments: dict[str, object] = {"cmd": cmd, "timeout_ms": timeout_ms}
        result = await mcp_client.call_tool("exec", arguments)
        return "\n".join(block.text for block in result.content if isinstance(block, TextContent))

    return FunctionTool(
        name="exec", description="Run a command in a scratch container. cmd is a list of strings (no shell).", func=exec
    )


# -- Helpers --


def _build_model_client(*, api: str, model: str) -> Any:
    if api == "openai":
        return OpenAIChatCompletionClient(model=model)
    if api == "anthropic":
        return AnthropicClient(model=model)
    raise ValueError(f"Unsupported API: {api!r}")


# -- Main game loop --

_MAX_STEPS = 200  # Safety cap to prevent infinite loops.


async def run_game(
    *,
    variant_name: str,
    model: str,
    api: str,
    output_dir: Path,
    exec_tool: FunctionTool | None = None,
    model_client: Any | None = None,
    no_skill: bool = False,
) -> RunSummary:
    """Execute one Twenty Questions game and persist results."""
    variant = VARIANTS[variant_name]
    sim_system = load_sim_prompt(secret=variant.secret, turn_limit=variant.turn_limit)
    guesser_system = build_guesser_system(
        skill="" if no_skill else load_skill_prompt(), has_scratch=exec_tool is not None
    )
    opening = first_user_message(variant.domain_description, variant.turn_limit)

    owns_client = model_client is None
    if model_client is None:
        model_client = _build_model_client(api=api, model=model)

    game = GameContext(turn_limit=variant.turn_limit)

    # Simulator state
    sim_history: list[Message] = [Message("system", [sim_system])]
    sim_tools = _make_sim_tools(game)

    # Guesser tools = game tools + optional exec
    game_tools = _make_game_tools(game=game, model_client=model_client, sim_history=sim_history, sim_tools=sim_tools)
    all_guesser_tools = list(game_tools)
    if exec_tool:
        all_guesser_tools.append(exec_tool)
    guesser_tool_map = {t.name: t for t in all_guesser_tools}

    # Guesser conversation history
    guesser_history: list[Message] = [Message("system", [guesser_system]), Message("user", [opening])]

    # Main loop: call guesser LLM with tool_choice=required, execute tools, repeat.
    for _ in range(_MAX_STEPS):
        if game.result is not None:
            break

        response = await model_client.get_response(
            guesser_history,
            options={"tools": all_guesser_tools, "tool_choice": "required", "allow_multiple_tool_calls": False},
        )

        function_calls = _extract_function_calls(response)
        if not function_calls:
            # Shouldn't happen with tool_choice=required, but handle gracefully.
            guesser_history.append(response.messages[0])
            continue

        guesser_history.append(response.messages[0])

        results: list[Content] = []
        for fc in function_calls:
            tool = guesser_tool_map[fc.name]
            args = json.loads(fc.arguments) if isinstance(fc.arguments, str) else (fc.arguments or {})
            try:
                tool_result = await tool.invoke(arguments=args)
                content = tool_result[0].text if tool_result else ""
            except Exception as e:
                # Return validation/execution errors to the model so it can retry.
                content = f"Error: {e}"
                logger.warning("Tool %s error: %s", fc.name, e)
            results.append(Content.from_function_result(fc.call_id, result=content))
        guesser_history.append(Message("tool", results))

    if game.result is None:
        game.result = Timeout(limit=game.turn_limit)

    result_val = game.result
    turns = result_val.limit if isinstance(result_val, Timeout) else result_val.turns

    calls_path, summary_path = run_output_paths(f"af_{variant_name}", output_dir)
    with calls_path.open("w") as f:
        for entry in game.log_entries:
            f.write(entry.model_dump_json() + "\n")

    summary = RunSummary(
        eval_name=variant_name,
        framework="agent_framework",
        model=model,
        api=api,
        turns=turns,
        result=result_val,
        invalid_input_count=game.invalid_input_count,
    )
    save_summary(summary=summary, summary_path=summary_path)

    if owns_client and hasattr(model_client, "close"):
        await model_client.close()
    return summary


async def _async_main(args: argparse.Namespace) -> None:
    output_dir = output_dir_from_args(args)

    async with scratch_exec_server() as server, Client(server) as mcp_client:
        exec_tool = _make_exec_tool(mcp_client)
        summary = await run_game(
            variant_name=args.variant,
            model=args.model,
            api=args.api,
            output_dir=output_dir,
            exec_tool=exec_tool,
            no_skill=getattr(args, "no_skill", False),
        )
    logger.info("Result: %s", summary.result.model_dump_json())


def main() -> None:
    parser = argparse.ArgumentParser(description="Twenty Questions — Agent Framework")
    add_common_args(parser)
    parser.add_argument("--no-skill", action="store_true", help="Run without info-gathering skill prompt (baseline)")
    args = parser.parse_args()
    resolve_args(args)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    asyncio.run(_async_main(args))


if __name__ == "__main__":
    main()
