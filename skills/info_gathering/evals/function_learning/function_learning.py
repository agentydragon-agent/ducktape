"""Function learning eval using Microsoft Agent Framework.

The model plays a function-learning game: each turn it queries one input of a
secret boolean function and submits a Python program guess. The scaffold evaluates
the program against all 2^N inputs in a Docker container and reports Hamming loss.
"""

import argparse
import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any, Literal, cast

import aiodocker
from agent_framework import ChatResponse, Content, FunctionTool, Message, UsageDetails
from agent_framework.anthropic import AnthropicClient
from agent_framework.openai import OpenAIChatCompletionClient
from fastmcp.client import Client
from mcp.types import TextContent
from pydantic import BaseModel

from skills.info_gathering.evals.docker_exec import scratch_exec_server
from skills.info_gathering.evals.function_learning.functions import FUNCTIONS, SecretFunction
from skills.info_gathering.evals.function_learning.prompts import build_system_prompt, first_user_message
from skills.info_gathering.evals.function_learning.result_types import (
    FunctionLearningResult,
    RunSummary,
    TokenUsage,
    TurnResult,
)
from skills.info_gathering.evals.function_learning.scoring import EVAL_TIMEOUT_S, evaluate_program
from skills.info_gathering.evals.twenty_questions.prompts import load_skill_prompt
from skills.info_gathering.evals.twenty_questions.x.shared.output import run_output_paths

logger = logging.getLogger(__name__)

_MAX_STEPS = 200


# --- Structured log entry types (written to calls.jsonl) ---


class GameStartLog(BaseModel):
    kind: Literal["game_start"] = "game_start"
    timestamp: str
    function_name: str
    n_bits: int
    m_bits: int
    no_skill: bool
    system_prompt: str
    opening_message: str


class FunctionCallLog(BaseModel):
    id: str
    name: str
    arguments: str  # raw JSON string as returned by the model


class LlmResponseLog(BaseModel):
    kind: Literal["llm_response"] = "llm_response"
    timestamp: str
    text: str | None
    tool_calls: list[FunctionCallLog] | None
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int | None
    cache_creation_tokens: int | None


class ToolResultLog(BaseModel):
    kind: Literal["tool_result"] = "tool_result"
    timestamp: str
    tool_name: str
    call_id: str
    arguments: dict
    result: str


class GameEndLog(BaseModel):
    kind: Literal["game_end"] = "game_end"
    timestamp: str
    turns: int
    solved_at_turn: int | None
    total_hamming_loss: int


# --- Game state ---


@dataclass
class GameContext:
    turn_limit: int
    log_file: IO[str]
    turn: int = 0
    solved: bool = False
    turn_results: list[TurnResult] = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cache_creation_tokens: int = 0

    @property
    def finished(self) -> bool:
        return self.turn >= self.turn_limit or self.solved

    def log(self, entry: BaseModel) -> None:
        self.log_file.write(entry.model_dump_json() + "\n")
        self.log_file.flush()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _extract_function_calls(response: ChatResponse) -> list[Content]:
    """Extract function call Content items from a ChatResponse."""
    msg = response.messages[0]
    return [c for c in msg.contents if c.type == "function_call"]


def _extract_usage(response: ChatResponse) -> UsageDetails | None:
    return response.usage_details


def _make_play_turn_tool(
    game: GameContext, secret_fn: SecretFunction, scoring_container: aiodocker.docker.DockerContainer
) -> FunctionTool:
    async def play_turn(query: int, program: str) -> str:
        """Query the secret function on one input and submit a program guess.

        Args:
            query: Integer in [0, max_input] to evaluate f on.
            program: Python program that takes no input and prints one line per
                     input (0 to max_input), each a decimal integer in [0, max_output].
        """
        if not (0 <= query <= secret_fn.max_input):
            return json.dumps({"error": f"query must be in [0, {secret_fn.max_input}], got {query}"})

        game.turn += 1
        query_result = secret_fn.evaluate(query)
        logger.info("Turn %d: query=%d -> %d", game.turn, query, query_result)

        scoring = await evaluate_program(scoring_container, program, secret_fn)
        score = scoring.score

        if score.hamming_loss == 0:
            game.solved = True

        game.turn_results.append(TurnResult(turn=game.turn, query=query, query_result=query_result, score=score))
        logger.info("Turn %d: hamming_loss=%d (eval %.1fs)", game.turn, score.hamming_loss, scoring.total_eval_s)

        response: dict[str, object] = {
            "turn": game.turn,
            "turns_remaining": game.turn_limit - game.turn,
            "query_result": f"f({query}) = {query_result}",
            "hamming_loss": score.hamming_loss,
            "total_possible_loss": (secret_fn.max_input + 1) * secret_fn.m,
        }
        if game.solved:
            response["game_over"] = "Solved! Your program is correct for all inputs."
        if score.has_errors:
            response["error_summary"] = {
                "parse_errors": score.parse_errors,
                "out_of_range": score.out_of_range,
                "missing_lines": score.missing_lines,
            }
        if score.examples:
            response["error_examples"] = [{"line": e.line, "error": e.error} for e in score.examples]

        return json.dumps(response, indent=2)

    return FunctionTool(
        name="play_turn",
        description=(
            "Query the secret function on one input and submit your program guess. "
            "The program takes no input and prints one output per line for inputs 0..max_input."
        ),
        func=play_turn,
    )


def make_exec_tool(mcp_client: Client) -> FunctionTool:
    async def exec(cmd: list[str], timeout_ms: int = 30000) -> str:
        """Run a command in a scratch container for computation."""
        arguments: dict[str, object] = {"cmd": cmd, "timeout_ms": timeout_ms}
        result = await mcp_client.call_tool("exec", arguments)
        return "\n".join(block.text for block in result.content if isinstance(block, TextContent))

    return FunctionTool(
        name="exec", description="Run a command in a scratch container. cmd is a list of strings (no shell).", func=exec
    )


def _build_model_client(*, api: str, model: str) -> Any:
    if api == "openai":
        return OpenAIChatCompletionClient(model=model)
    if api == "anthropic":
        return AnthropicClient(model=model)
    raise ValueError(f"Unsupported API: {api!r}")


_NO_HINT = "The function class is unknown. You must discover its structure from queries alone."


async def run_game(
    *,
    function_name: str,
    hint: bool,
    turn_limit: int,
    model: str,
    api: str,
    output_dir: Path,
    exec_tool: FunctionTool,
    scoring_container: aiodocker.docker.DockerContainer,
    model_client: Any | None = None,
    no_skill: bool = False,
) -> RunSummary:
    """Execute one function learning game and persist results."""
    secret_fn = FUNCTIONS[function_name]
    description = secret_fn.description if hint else _NO_HINT

    system = build_system_prompt(skill="" if no_skill else load_skill_prompt(), has_scratch=True)
    opening = first_user_message(secret_fn, turn_limit, description, eval_timeout_s=EVAL_TIMEOUT_S)

    owns_client = model_client is None
    if model_client is None:
        model_client = _build_model_client(api=api, model=model)

    calls_path, summary_path = run_output_paths(f"fl_{function_name}_{'hint' if hint else 'nohint'}", output_dir)

    with calls_path.open("w") as log_f:
        game = GameContext(turn_limit=turn_limit, log_file=log_f)
        play_turn_tool = _make_play_turn_tool(game, secret_fn, scoring_container)
        all_tools = [play_turn_tool, exec_tool]
        tool_map = {t.name: t for t in all_tools}
        game.log(
            GameStartLog(
                timestamp=_now(),
                function_name=function_name,
                n_bits=secret_fn.n,
                m_bits=secret_fn.m,
                no_skill=no_skill,
                system_prompt=system,
                opening_message=opening,
            )
        )

        history: list[Message] = [Message("system", [system]), Message("user", [opening])]

        for _ in range(_MAX_STEPS):
            if game.finished:
                break

            response = await model_client.get_response(
                history, options={"tools": all_tools, "tool_choice": "required", "allow_multiple_tool_calls": False}
            )

            usage = _extract_usage(response)
            if usage:
                game.total_input_tokens += usage.get("input_token_count") or 0
                game.total_output_tokens += usage.get("output_token_count") or 0
                cache_read = usage.get("anthropic.cache_read_input_tokens")
                cache_create = usage.get("anthropic.cache_creation_input_tokens")
                game.total_cache_read_tokens += cast(int, cache_read) if cache_read is not None else 0
                game.total_cache_creation_tokens += cast(int, cache_create) if cache_create is not None else 0

            function_calls = _extract_function_calls(response)

            if not function_calls:
                text_content = response.messages[0].text
                cache_read = usage.get("anthropic.cache_read_input_tokens") if usage else None
                cache_creation = usage.get("anthropic.cache_creation_input_tokens") if usage else None
                game.log(
                    LlmResponseLog(
                        timestamp=_now(),
                        text=text_content,
                        tool_calls=None,
                        input_tokens=usage.get("input_token_count", 0) or 0 if usage else 0,
                        output_tokens=usage.get("output_token_count", 0) or 0 if usage else 0,
                        cache_read_tokens=cache_read,
                        cache_creation_tokens=cache_creation,
                    )
                )
                history.append(response.messages[0])
                continue

            assert len(function_calls) == 1, f"expected 1 tool call, got {len(function_calls)}"
            fc = function_calls[0]
            cache_read = usage.get("anthropic.cache_read_input_tokens") if usage else None
            cache_creation = usage.get("anthropic.cache_creation_input_tokens") if usage else None
            game.log(
                LlmResponseLog(
                    timestamp=_now(),
                    text=None,
                    tool_calls=[
                        FunctionCallLog(
                            id=fc.call_id,
                            name=fc.name,
                            arguments=fc.arguments if isinstance(fc.arguments, str) else json.dumps(fc.arguments),
                        )
                    ],
                    input_tokens=usage.get("input_token_count", 0) or 0 if usage else 0,
                    output_tokens=usage.get("output_token_count", 0) or 0 if usage else 0,
                    cache_read_tokens=cache_read,
                    cache_creation_tokens=cache_creation,
                )
            )
            history.append(response.messages[0])

            results: list[Content] = []
            for fc in function_calls:
                assert fc.call_id is not None, f"function_call missing call_id: {fc}"
                tool = tool_map.get(fc.name) if fc.name is not None else None
                args = json.loads(fc.arguments) if isinstance(fc.arguments, str) else (fc.arguments or {})
                if tool is None:
                    content = f"Error: unknown tool '{fc.name}'"
                    logger.warning("Unknown tool name: %s", fc.name)
                else:
                    try:
                        tool_result = await tool.invoke(arguments=args)
                        content = tool_result[0].text if tool_result and tool_result[0].text else ""
                    except Exception as e:
                        content = f"Error: {e}"
                        logger.warning("Tool %s error: %s", fc.name, e)
                game.log(
                    ToolResultLog(
                        timestamp=_now(), tool_name=fc.name, call_id=fc.call_id, arguments=args, result=content
                    )
                )
                results.append(Content.from_function_result(fc.call_id, result=content))
            history.append(Message("tool", results))

        per_turn = [tr.score.hamming_loss for tr in game.turn_results]
        per_turn += [0] * (turn_limit - len(per_turn))
        total_hamming = sum(per_turn)

        game.log(
            GameEndLog(
                timestamp=_now(),
                turns=game.turn,
                solved_at_turn=game.turn if game.solved else None,
                total_hamming_loss=total_hamming,
            )
        )

    fl_result = FunctionLearningResult(
        total_hamming_loss=total_hamming, per_turn_losses=per_turn, solved_at_turn=game.turn if game.solved else None
    )

    summary = RunSummary(
        eval_name=function_name,
        framework="agent_framework",
        model=model,
        api=api,
        turns=game.turn,
        result=fl_result,
        function_name=secret_fn.name,
        n_bits=secret_fn.n,
        m_bits=secret_fn.m,
        usage=TokenUsage(
            input_tokens=game.total_input_tokens,
            output_tokens=game.total_output_tokens,
            cache_read_input_tokens=game.total_cache_read_tokens,
            cache_creation_input_tokens=game.total_cache_creation_tokens,
        ),
    )
    summary_path.write_text(summary.model_dump_json(indent=2))
    logger.info("Saved results to %s", summary_path.parent)

    if owns_client and hasattr(model_client, "close"):
        await model_client.close()
    return summary


async def _async_main(args: argparse.Namespace) -> None:
    output_dir = Path(args.output_dir) if args.output_dir else Path("eval_results") / "function_learning"
    output_dir.mkdir(parents=True, exist_ok=True)

    async with scratch_exec_server() as scratch_server, Client(scratch_server) as scratch_client:
        exec_tool = make_exec_tool(scratch_client)

        container_name = f"fl-scoring-{uuid.uuid4().hex[:8]}"
        async with aiodocker.Docker() as docker:
            container = await docker.containers.run(
                config={"Image": "python:3.13-slim", "Cmd": ["sleep", "3600"]}, name=container_name
            )
            try:
                summary = await run_game(
                    function_name=args.function,
                    hint=not args.no_hint,
                    model=args.model,
                    api=args.api,
                    output_dir=output_dir,
                    exec_tool=exec_tool,
                    scoring_container=container,
                    no_skill=args.no_skill,
                    turn_limit=args.turn_limit,
                )
            finally:
                await container.delete(force=True)
    logger.info("Result: %s", summary.result.model_dump_json())


def main() -> None:
    parser = argparse.ArgumentParser(description="Function Learning Eval — Agent Framework")
    parser.add_argument("--function", choices=list(FUNCTIONS), required=True)
    parser.add_argument("--no-hint", action="store_true")
    parser.add_argument("--model", required=True)
    parser.add_argument("--api", choices=["openai", "anthropic"], default="anthropic")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--no-skill", action="store_true")
    parser.add_argument("--turn-limit", type=int, required=True)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(_async_main(args))


if __name__ == "__main__":
    main()
