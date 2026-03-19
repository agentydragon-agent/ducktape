"""Twenty Questions eval variants.

Usage:
  bazel run //skills/info_gathering/evals/twenty_questions:twenty_questions_bin -- --variant states
  bazel run //skills/info_gathering/evals/twenty_questions:twenty_questions_bin -- \\
    --variant states --model gpt-oss:20b --base-url https://ollama.allegedly.works/v1
"""

import argparse
import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from agent_core.agent import Agent
from agent_core.direct_provider import DirectToolProvider
from agent_core.events import AssistantText, Response, ToolCall
from agent_core.handler import BaseHandler
from agent_core.loop_control import AllowAnyToolOrTextMessage, RequireAnyTool
from agent_core.tool_provider import ToolProvider
from openai_utils.model import OpenAIModelProto, SystemMessage, UserMessage
from skills.info_gathering.evals.docker_scratch import load_scratch_image, scratch_container
from skills.info_gathering.evals.harness import (
    LogEntry,
    RunSummary,
    add_common_args,
    build_agent_system,
    load_skill,
    model_from_args,
    output_dir_from_args,
    save_results,
)
from util.bazel.runfiles import get_required_path

logger = logging.getLogger(__name__)

_SIM_RLOCATION = "_main/skills/info_gathering/evals/twenty_questions/sim.txt"

_SCRATCH_SYSTEM_NOTE = """\
You have access to an `exec` tool — a private Docker container for scratch computation. \
Use it freely: run code, track hypothesis spaces, write notes, organize your reasoning. \
Calling this tool does NOT use up one of your question turns."""

# Safety cap: max scratch tool call rounds per agent turn before we give up.
_MAX_SCRATCH_STEPS = 20


class Correct(BaseModel):
    turns: int


class Timeout(BaseModel):
    limit: int


class AnswerInput(BaseModel):
    response: Literal["yes", "no", "sort_of"]
    model_config = ConfigDict(extra="forbid")


@dataclass
class SimAction:
    """Records the sim's game action from a tool call."""

    tool_name: str
    answer: str | None = None


@dataclass
class Variant:
    domain_description: str
    secret: str
    turn_limit: int = 20


VARIANTS: dict[str, Variant] = {
    "states": Variant(domain_description="a US state", secret="New Mexico"),
    "wide": Variant(
        domain_description="a thing — could be anything: object, place, concept, activity, anything",
        secret="a sourdough starter",
        turn_limit=25,
    ),
}


class _TextCaptureHandler(BaseHandler):
    """Captures assistant text produced during an agent step."""

    def __init__(self) -> None:
        self._text: str | None = None

    def on_assistant_text_event(self, evt: AssistantText) -> None:
        self._text = (self._text or "") + evt.text

    def take(self) -> str | None:
        """Return captured text and reset state."""
        text = self._text
        self._text = None
        return text.strip() if text else None


class _TurnLogHandler(BaseHandler):
    """Records a LogEntry per LLM response call for eval output.

    on_response fires after _process_resp_output, so self._text and self._tool_calls
    already hold the content from the current response when the entry is flushed.
    """

    def __init__(
        self,
        *,
        eval_name: str,
        player: Literal["agent", "simulator"],
        log_entries: list[LogEntry],
        turn_getter: Callable[[], int],
    ) -> None:
        self._eval_name = eval_name
        self._player = player
        self._log_entries = log_entries
        self._turn_getter = turn_getter
        self._text = ""
        self._tool_calls: list[dict] = []

    def on_assistant_text_event(self, evt: AssistantText) -> None:
        self._text += evt.text

    def on_tool_call_event(self, evt: ToolCall) -> None:
        self._tool_calls.append({"id": evt.call_id, "name": evt.name, "arguments": evt.args_json})

    def on_response(self, evt: Response) -> None:
        self._log_entries.append(
            LogEntry(
                timestamp=datetime.now(UTC).isoformat(),
                eval_name=self._eval_name,
                player=self._player,
                turn=self._turn_getter(),
                model=evt.model,
                content=self._text,
                tool_calls=list(self._tool_calls),
                stop_reason="tool_calls" if self._tool_calls else "stop",
            )
        )
        self._text = ""
        self._tool_calls = []


class _TwentyQuestionsRunner:
    """Runs a single 20Q eval game with two Agent instances communicating in a loop."""

    def __init__(
        self,
        *,
        name: str,
        model: OpenAIModelProto,
        agent_system: str,
        sim_system: str,
        agent_tool_provider: ToolProvider,
    ) -> None:
        self.name = name
        self.model = model
        self.log_entries: list[LogEntry] = []
        self._current_turn = 0

        # Sim tool provider: closures capture sim_action
        self.sim_action: SimAction | None = None
        sim_provider = DirectToolProvider()

        @sim_provider.tool
        def answer(args: AnswerInput) -> str:
            """Answer the player's yes/no question."""
            self.sim_action = SimAction(tool_name="answer", answer=args.response)
            return args.response

        @sim_provider.tool
        def correct_answer() -> None:
            """The player correctly guessed the secret."""
            self.sim_action = SimAction(tool_name="correct_answer")

        agent_log = _TurnLogHandler(
            eval_name=name, player="agent", log_entries=self.log_entries, turn_getter=lambda: self._current_turn
        )
        sim_log = _TurnLogHandler(
            eval_name=name, player="simulator", log_entries=self.log_entries, turn_getter=lambda: self._current_turn
        )
        self._text_capture = _TextCaptureHandler()

        self._agent = Agent(
            tool_provider=agent_tool_provider,
            client=model,
            parallel_tool_calls=False,
            handlers=[agent_log, self._text_capture],
            tool_policy=AllowAnyToolOrTextMessage(),
        )
        self._agent.process_message(SystemMessage.text(agent_system))

        self._sim = Agent(
            tool_provider=sim_provider,
            client=model,
            parallel_tool_calls=False,
            handlers=[sim_log],
            tool_policy=RequireAnyTool(),
        )
        self._sim.process_message(SystemMessage.text(sim_system))

    async def _agent_turn(self) -> str | None:
        """Step the agent until it produces text. Returns the text or None if stuck."""
        for _ in range(_MAX_SCRATCH_STEPS):
            await self._agent.step()
            text = self._text_capture.take()
            if text:
                return text
        logger.warning("Agent hit scratch step limit without producing text")
        return None

    async def _sim_turn(self, question: str) -> SimAction | None:
        """Feed question to sim and step once. Returns the sim's action or None on failure."""
        self.sim_action = None
        self._sim.process_message(UserMessage.text(question))
        await self._sim.step()
        if self.sim_action is None:
            logger.warning("Sim step produced no action (tool_choice=required was ignored)")
        return self.sim_action

    async def run(self, *, first_user_message: str, turn_limit: int, output_dir: Path) -> RunSummary:
        """Run the full game loop and return summary."""
        self._agent.process_message(UserMessage.text(first_user_message))

        result: Correct | Timeout | None = None
        turn = 0
        for turn in range(1, turn_limit + 1):
            self._current_turn = turn
            logger.info("Turn %d...", turn)

            agent_text = await self._agent_turn()
            if not agent_text:
                result = Timeout(limit=turn_limit)
                break

            action = await self._sim_turn(agent_text)
            if action is None:
                result = Timeout(limit=turn_limit)
                break

            if action.tool_name == "correct_answer":
                result = Correct(turns=turn)
                break

            assert action.answer is not None
            self._agent.process_message(UserMessage.text(action.answer))
        else:
            result = Timeout(limit=turn_limit)

        if result is None:
            result = Timeout(limit=turn_limit)

        summary = RunSummary(eval_name=self.name, model=self.model.model, turns=turn, result=result)
        save_results(name=self.name, log_entries=self.log_entries, summary=summary, output_dir=output_dir)
        return summary


async def run_twenty_questions(
    *,
    name: str,
    model: OpenAIModelProto,
    agent_system: str,
    first_user_message: str,
    sim_system: str,
    turn_limit: int = 20,
    output_dir: Path,
    agent_tool_provider: ToolProvider,
) -> RunSummary:
    """Run a 20 Questions eval.

    Agent asks questions (optionally with scratch tools). Simulator answers via tool calls.
    Game ends when sim calls correct_answer or turns run out.
    """
    runner = _TwentyQuestionsRunner(
        name=name,
        model=model,
        agent_system=agent_system,
        sim_system=sim_system,
        agent_tool_provider=agent_tool_provider,
    )
    return await runner.run(first_user_message=first_user_message, turn_limit=turn_limit, output_dir=output_dir)


async def _async_main(args: argparse.Namespace) -> None:
    v = VARIANTS[args.variant]
    name = f"20q_{args.variant}"

    skill_text = load_skill()
    agent_system = build_agent_system(skill_text, extra_system=_SCRATCH_SYSTEM_NOTE)
    model = model_from_args(args)
    output_dir = output_dir_from_args(args)

    sim_template = get_required_path(_SIM_RLOCATION).read_text()
    sim_system = sim_template.format(secret=v.secret, turn_limit=v.turn_limit)

    first_user_message = (
        f"Play 20 Questions. I'm thinking of {v.domain_description}. "
        f"You have {v.turn_limit} yes/no questions. "
        "When confident, state: 'My answer is: [X]'."
    )

    logger.info("=" * 60)
    logger.info("  %s  |  %s", name, model.model)
    logger.info("=" * 60)

    image = load_scratch_image()
    async with scratch_container(image) as provider:
        summary = await run_twenty_questions(
            name=name,
            model=model,
            agent_system=agent_system,
            first_user_message=first_user_message,
            sim_system=sim_system,
            turn_limit=v.turn_limit,
            output_dir=output_dir,
            agent_tool_provider=provider,
        )
    logger.info("%s", summary)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    p = argparse.ArgumentParser(description="Twenty Questions eval")
    add_common_args(p)
    p.add_argument("--variant", choices=list(VARIANTS), required=True)
    args = p.parse_args()

    asyncio.run(_async_main(args))


if __name__ == "__main__":
    main()
