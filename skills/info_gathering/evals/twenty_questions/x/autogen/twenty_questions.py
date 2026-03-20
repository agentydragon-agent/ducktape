"""Twenty Questions game using AutoGen v0.4 core runtime with direct agent messaging.

Uses autogen_core's RoutedAgent and publish_message for inter-agent communication.
The simulator's tools ARE the communication mechanism — answer() publishes directly
to the guesser, correct_answer() ends the game by not publishing.
"""

import argparse
import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from autogen_core import (
    MessageContext,
    RoutedAgent,
    SingleThreadedAgentRuntime,
    TopicId,
    TypeSubscription,
    message_handler,
)
from autogen_core.models import (
    AssistantMessage,
    ChatCompletionClient,
    FunctionExecutionResult,
    FunctionExecutionResultMessage,
    SystemMessage,
    UserMessage,
)
from autogen_core.tools import FunctionTool
from autogen_ext.models.anthropic import AnthropicChatCompletionClient
from autogen_ext.models.openai import OpenAIChatCompletionClient
from fastmcp.client import Client
from mcp.types import TextContent

from skills.info_gathering.evals.twenty_questions.x.shared.cli import (
    add_common_args,
    output_dir_from_args,
    resolve_args,
)
from skills.info_gathering.evals.twenty_questions.x.shared.docker_exec import scratch_exec_server
from skills.info_gathering.evals.twenty_questions.x.shared.output import run_output_paths, save_summary
from skills.info_gathering.evals.twenty_questions.x.shared.prompts import (
    build_guesser_system,
    first_user_message,
    load_sim_prompt,
    load_skill_prompt,
)
from skills.info_gathering.evals.twenty_questions.x.shared.result_types import (
    Correct,
    LogEntry,
    Result,
    RunSummary,
    Timeout,
)
from skills.info_gathering.evals.twenty_questions.x.shared.variants import VARIANTS

logger = logging.getLogger(__name__)

GUESSER_TOPIC = TopicId(type="guesser", source="default")
SIMULATOR_TOPIC = TopicId(type="simulator", source="default")


# -- Message types for inter-agent communication --


@dataclass
class StartGame:
    """Kick off the game with the opening prompt."""

    opening: str


@dataclass
class QuestionForSimulator:
    """Guesser's question, sent to the simulator."""

    text: str


@dataclass
class AnswerForGuesser:
    """Simulator's answer, sent back to the guesser."""

    response: str


# -- Shared game state --


@dataclass
class GameContext:
    """Mutable game state shared between agents. Safe because the runtime is single-threaded."""

    turn_limit: int
    turn: int = 0
    result: Result | None = None
    log_entries: list[LogEntry] = field(default_factory=list)

    def record(
        self, player: Literal["guesser", "simulator"], content: str, tool_calls: list[dict[str, object]] | None = None
    ) -> None:
        self.log_entries.append(
            LogEntry(timestamp=datetime.now(UTC), player=player, content=content, tool_calls=tool_calls or [])
        )


# -- Guesser agent --


class GuesserAgent(RoutedAgent):
    def __init__(
        self,
        model_client: ChatCompletionClient,
        system_message: str,
        game: GameContext,
        exec_tools: list[FunctionTool] | None = None,
    ) -> None:
        super().__init__("Guesser agent")
        self._model = model_client
        self._history: list[SystemMessage | UserMessage | AssistantMessage | FunctionExecutionResultMessage] = [
            SystemMessage(content=system_message)
        ]
        self._game = game
        self._exec_tools = exec_tools or []
        self._exec_schemas = [t.schema for t in self._exec_tools]
        self._exec_map = {t.name: t for t in self._exec_tools}

    @message_handler
    async def handle_start(self, message: StartGame, ctx: MessageContext) -> None:
        self._history.append(UserMessage(content=message.opening, source="user"))
        await self._produce_question(ctx)

    @message_handler
    async def handle_answer(self, message: AnswerForGuesser, ctx: MessageContext) -> None:
        self._history.append(UserMessage(content=message.response, source="simulator"))
        await self._produce_question(ctx)

    async def _produce_question(self, ctx: MessageContext) -> None:
        self._game.turn += 1
        if self._game.turn > self._game.turn_limit:
            self._game.result = Timeout(limit=self._game.turn_limit)
            return  # Don't publish — runtime goes idle, game ends.

        question = await self._call_llm(ctx)
        self._game.record("guesser", question)
        logger.info("Guesser (turn %d): %s", self._game.turn, question[:200])
        await self.publish_message(QuestionForSimulator(text=question), SIMULATOR_TOPIC)

    async def _call_llm(self, ctx: MessageContext) -> str:
        """Call LLM, executing exec tools in a loop until it produces text."""
        while True:
            result = await self._model.create(
                self._history, tools=self._exec_schemas or [], cancellation_token=ctx.cancellation_token
            )

            if isinstance(result.content, str):
                self._history.append(AssistantMessage(content=result.content, source="guesser"))
                return result.content.strip()

            # Exec tool calls — execute and feed results back to LLM.
            function_calls = result.content
            self._history.append(AssistantMessage(content=function_calls, source="guesser"))
            exec_results: list[FunctionExecutionResult] = []
            for fc in function_calls:
                tool = self._exec_map[fc.name]
                args = json.loads(fc.arguments) if isinstance(fc.arguments, str) else fc.arguments
                tool_result = await tool.run_json(args, ctx.cancellation_token)
                exec_results.append(
                    FunctionExecutionResult(
                        call_id=fc.id, content=tool.return_value_as_string(tool_result), name=fc.name
                    )
                )
            self._history.append(FunctionExecutionResultMessage(content=exec_results))


# -- Simulator agent --


class SimulatorAgent(RoutedAgent):
    def __init__(self, model_client: ChatCompletionClient, system_message: str, game: GameContext) -> None:
        super().__init__("Simulator agent")
        self._model = model_client
        self._history: list[SystemMessage | UserMessage | AssistantMessage | FunctionExecutionResultMessage] = [
            SystemMessage(content=system_message)
        ]
        self._game = game
        self._tools = self._make_tools()
        self._tool_schemas = [t.schema for t in self._tools]
        self._tool_map = {t.name: t for t in self._tools}

    def _make_tools(self) -> list[FunctionTool]:
        agent = self
        game = self._game

        async def answer(response: Literal["yes", "no", "sort_of"]) -> str:
            """Answer the player's yes/no question."""
            game.record("simulator", response, [{"name": "answer", "args": {"response": response}}])
            logger.info("Simulator: %s", response)
            # The tool IS the inter-agent message — send answer directly to guesser.
            await agent.publish_message(AnswerForGuesser(response=response), GUESSER_TOPIC)
            return response

        async def correct_answer() -> str:
            """The player correctly guessed the secret."""
            game.result = Correct(turns=game.turn)
            game.record("simulator", "", [{"name": "correct_answer", "args": {}}])
            logger.info("Correct answer on turn %d!", game.turn)
            # Don't publish — runtime goes idle, game ends.
            return "correct"

        return [
            FunctionTool(answer, name="answer", description="Answer a yes/no question."),
            FunctionTool(correct_answer, name="correct_answer", description="The player guessed correctly."),
        ]

    @message_handler
    async def handle_question(self, message: QuestionForSimulator, ctx: MessageContext) -> None:
        self._history.append(UserMessage(content=message.text, source="guesser"))
        result = await self._model.create(
            self._history, tools=self._tool_schemas, tool_choice="required", cancellation_token=ctx.cancellation_token
        )

        if isinstance(result.content, str):
            raise RuntimeError(f"Simulator returned text instead of tool call: {result.content!r}")

        function_calls = result.content
        self._history.append(AssistantMessage(content=function_calls, source="simulator"))

        # Execute tools — answer() publishes to guesser, correct_answer() ends the game.
        exec_results: list[FunctionExecutionResult] = []
        for fc in function_calls:
            tool = self._tool_map[fc.name]
            args = json.loads(fc.arguments) if isinstance(fc.arguments, str) else fc.arguments
            tool_result = await tool.run_json(args, ctx.cancellation_token)
            exec_results.append(
                FunctionExecutionResult(call_id=fc.id, content=tool.return_value_as_string(tool_result), name=fc.name)
            )
        self._history.append(FunctionExecutionResultMessage(content=exec_results))


# -- MCP exec tool bridge --


def _make_exec_tool(mcp_client: Client) -> FunctionTool:
    """Create a FunctionTool that delegates to the MCP exec tool via fastmcp.Client."""

    async def exec(cmd: list[str], cwd: str | None = None, timeout_ms: int = 30000) -> str:
        """Run a command in a scratch container."""
        arguments: dict[str, object] = {"cmd": cmd, "timeout_ms": timeout_ms}
        if cwd is not None:
            arguments["cwd"] = cwd
        result = await mcp_client.call_tool("exec", arguments)
        return "\n".join(block.text for block in result.content if isinstance(block, TextContent))

    return FunctionTool(
        exec, name="exec", description="Run a command in a scratch container. cmd is a list of strings (no shell)."
    )


# -- Helpers --


def _build_model_client(*, api: str, model: str) -> ChatCompletionClient:
    if api == "openai":
        return OpenAIChatCompletionClient(model=model)
    if api == "anthropic":
        return AnthropicChatCompletionClient(model=model)
    raise ValueError(f"Unsupported API: {api!r}")


# -- Public API --


async def run_game(
    *,
    variant_name: str,
    model: str,
    api: str,
    output_dir: Path,
    exec_tool: FunctionTool | None = None,
    model_client: ChatCompletionClient | None = None,
) -> RunSummary:
    """Execute one Twenty Questions game and persist results."""
    variant = VARIANTS[variant_name]
    sim_system = load_sim_prompt(secret=variant.secret, turn_limit=variant.turn_limit)
    skill_text = load_skill_prompt()
    guesser_system = build_guesser_system(skill_text)
    opening = first_user_message(variant.domain_description, variant.turn_limit)

    owns_client = model_client is None
    if model_client is None:
        model_client = _build_model_client(api=api, model=model)

    game = GameContext(turn_limit=variant.turn_limit)
    exec_tools = [exec_tool] if exec_tool else []

    runtime = SingleThreadedAgentRuntime()
    await GuesserAgent.register(
        runtime,
        "guesser",
        lambda: GuesserAgent(
            model_client=model_client, system_message=guesser_system, game=game, exec_tools=exec_tools
        ),
    )
    await SimulatorAgent.register(
        runtime, "simulator", lambda: SimulatorAgent(model_client=model_client, system_message=sim_system, game=game)
    )
    await runtime.add_subscription(TypeSubscription("guesser", "guesser"))
    await runtime.add_subscription(TypeSubscription("simulator", "simulator"))

    runtime.start()
    await runtime.publish_message(StartGame(opening=opening), GUESSER_TOPIC)
    await runtime.stop_when_idle()

    result = game.result
    assert result is not None, "Game ended without setting result"
    turns = result.limit if isinstance(result, Timeout) else result.turns

    calls_path, summary_path = run_output_paths(f"autogen_{variant_name}", output_dir)
    with calls_path.open("w") as f:
        for entry in game.log_entries:
            f.write(entry.model_dump_json() + "\n")

    summary = RunSummary(eval_name=variant_name, framework="autogen", model=model, api=api, turns=turns, result=result)
    save_summary(summary=summary, summary_path=summary_path)

    if owns_client:
        await model_client.close()
    return summary


async def _async_main(args: argparse.Namespace) -> None:
    output_dir = output_dir_from_args(args)

    async with scratch_exec_server() as server, Client(server) as mcp_client:
        exec_tool = _make_exec_tool(mcp_client)
        summary = await run_game(
            variant_name=args.variant, model=args.model, api=args.api, output_dir=output_dir, exec_tool=exec_tool
        )
    logger.info("Result: %s", summary.result.model_dump_json())


def main() -> None:
    parser = argparse.ArgumentParser(description="Twenty Questions — AutoGen v0.4")
    add_common_args(parser)
    args = parser.parse_args()
    resolve_args(args)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    asyncio.run(_async_main(args))


if __name__ == "__main__":
    main()
