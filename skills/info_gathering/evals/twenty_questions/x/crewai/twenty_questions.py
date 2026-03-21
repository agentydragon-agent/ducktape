"""Twenty Questions eval using CrewAI.

Two-agent game: a Guesser asks yes/no questions, a Simulator holds a secret
and responds via tool calls only. Uses BaseTool with typed Pydantic schemas
for simulator actions and a simple turn-based loop for game orchestration.

Usage:
  bazel run //skills/info_gathering/evals/twenty_questions/x/crewai:twenty_questions_crewai_bin -- \
    --variant states --api openai --model gpt-4o-mini
"""

import argparse
import asyncio
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from crewai import Agent, Crew, Process, Task
from crewai.crews.crew_output import CrewOutput
from crewai.tools import BaseTool
from fastmcp.client import Client
from pydantic import BaseModel, Field, PrivateAttr

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


class SimulatorToolState:
    """Per-turn mutable state shared between simulator tools and the game loop."""

    def __init__(self) -> None:
        self.result: dict[str, object] | None = None


class AnswerInput(BaseModel):
    """Input schema for the answer tool."""

    response: Literal["yes", "no", "sort_of"] = Field(description="The answer: 'yes', 'no', or 'sort_of'.")


class AnswerTool(BaseTool):
    """Answer the player's yes/no question."""

    name: str = "answer"
    description: str = "Answer the player's yes/no question. Response must be 'yes', 'no', or 'sort_of'."
    args_schema: type[BaseModel] = AnswerInput

    _state: SimulatorToolState = PrivateAttr()

    def __init__(self, *, state: SimulatorToolState) -> None:
        super().__init__(
            name="answer",
            description="Answer the player's yes/no question. Response must be 'yes', 'no', or 'sort_of'.",
        )
        self._state = state

    def _run(self, response: str) -> str:
        self._state.result = {"name": "answer", "args": {"response": response}}
        return response


class CorrectAnswerTool(BaseTool):
    """Signal that the player correctly guessed the secret."""

    name: str = "correct_answer"
    description: str = "Call this when the player correctly guessed the secret."

    _state: SimulatorToolState = PrivateAttr()

    def __init__(self, *, state: SimulatorToolState) -> None:
        super().__init__(name="correct_answer", description="Call this when the player correctly guessed the secret.")
        self._state = state

    def _run(self) -> str:
        self._state.result = {"name": "correct_answer", "args": {}}
        return "correct"


class ExecInput(BaseModel):
    cmd: list[str] = Field(description="Command array (no shell). Use ['sh', '-c', '...'] for shell features.")
    cwd: str | None = Field(default=None, description="Working directory inside container (None = default).")
    timeout_ms: int = Field(default=30000, description="Timeout in milliseconds.")


class ExecTool(BaseTool):
    """Run a command in a scratch Docker container via MCP exec tool."""

    name: str = "exec"
    description: str = "Run a command in a scratch container. cmd is a list of strings (no shell)."
    args_schema: type[BaseModel] = ExecInput

    _mcp_client: Any = PrivateAttr()
    _loop: Any = PrivateAttr()

    def __init__(self, *, mcp_client: Client, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__(
            name="exec", description="Run a command in a scratch container. cmd is a list of strings (no shell)."
        )
        self._mcp_client = mcp_client
        self._loop = loop

    def _run(self, cmd: list[str], cwd: str | None = None, timeout_ms: int = 30000) -> str:
        arguments: dict[str, Any] = {"cmd": cmd, "timeout_ms": timeout_ms}
        if cwd is not None:
            arguments["cwd"] = cwd
        future = asyncio.run_coroutine_threadsafe(self._mcp_client.call_tool("exec", arguments), self._loop)
        result = future.result()
        return "\n".join(block.text for block in result.content if hasattr(block, "text"))


def crewai_model_name(api: str, model: str) -> str:
    """Return the model name in CrewAI/LiteLLM format."""
    if api == "anthropic":
        return f"anthropic/{model}"
    return model


def _make_agents(
    *, api: str, model: str, guesser_system: str, sim_system: str, extra_guesser_tools: list[BaseTool] | None = None
) -> tuple[Agent, Agent]:
    """Create the guesser and simulator CrewAI agents."""
    llm_name = crewai_model_name(api, model)

    guesser = Agent(
        role="Guesser",
        goal="Guess the secret by asking yes/no questions",
        backstory=guesser_system,
        llm=llm_name,
        tools=extra_guesser_tools or [],
        verbose=False,
    )

    simulator = Agent(
        role="Simulator",
        goal="Answer the player's questions honestly using only the provided tools",
        backstory=sim_system,
        llm=llm_name,
        verbose=False,
    )

    return guesser, simulator


def _run_guesser_turn(guesser: Agent, prompt: str) -> str:
    """Execute a single guesser turn and return the text output."""
    task = Task(
        description=prompt,
        expected_output="A yes/no question or a final guess in the form 'My answer is: [X]'",
        agent=guesser,
    )
    crew = Crew(agents=[guesser], tasks=[task], process=Process.sequential, verbose=False)
    result = crew.kickoff()
    if not isinstance(result, CrewOutput):
        return str(result).strip()
    return str(result.raw).strip()


def _run_simulator_turn(simulator: Agent, question: str) -> dict[str, object] | None:
    """Execute a single simulator turn and return the tool call dict, or None."""
    state = SimulatorToolState()
    tools = [AnswerTool(state=state), CorrectAnswerTool(state=state)]

    task = Task(
        description=(
            f"The player said: {question}\n\n"
            "You MUST use one of your tools to respond. "
            "Use 'answer' for yes/no questions, or 'correct_answer' if the player guessed correctly."
        ),
        expected_output="A tool call response",
        agent=simulator,
        tools=tools,
    )
    crew = Crew(agents=[simulator], tasks=[task], process=Process.sequential, verbose=False)
    crew.kickoff()
    return state.result


GameOutcome = Correct | Timeout


def run_game_loop(
    *, guesser: Agent, simulator: Agent, first_msg: str, turn_limit: int
) -> tuple[GameOutcome, int, list[LogEntry]]:
    """Run the turn-based game loop. Returns (result, turns_played, log_entries)."""
    log_entries: list[LogEntry] = []
    guesser_prompt = first_msg
    result: GameOutcome = Timeout(limit=turn_limit)
    turn = 0

    for turn in range(1, turn_limit + 1):
        logger.info("Turn %d...", turn)

        # Guesser turn
        guesser_text = _run_guesser_turn(guesser, guesser_prompt)
        log_entries.append(LogEntry(timestamp=datetime.now(UTC), player="guesser", content=guesser_text))

        # Simulator turn
        tool_result = _run_simulator_turn(simulator, guesser_text)
        if tool_result is None:
            logger.warning("Simulator produced no tool call on turn %d", turn)
            break

        is_correct = tool_result["name"] == "correct_answer"
        sim_reply = "correct" if is_correct else str(tool_result["args"]["response"])  # type: ignore[index]

        log_entries.append(
            LogEntry(timestamp=datetime.now(UTC), player="simulator", content=sim_reply, tool_calls=[tool_result])
        )

        if is_correct:
            result = Correct(turns=turn)
            break

        # Prepare next guesser prompt
        guesser_prompt = f"The answer to your last question was: {sim_reply}\n\nAsk your next question."

    return result, turn, list(log_entries)


def run_twenty_questions_crewai(
    *,
    name: str,
    api: str,
    model_name: str,
    guesser_system: str,
    sim_system: str,
    first_msg: str,
    turn_limit: int,
    output_dir: Path,
    exec_tool: ExecTool | None = None,
) -> RunSummary:
    """Run a full 20 Questions game with CrewAI and return a summary."""
    calls_path, summary_path = run_output_paths(name, output_dir)

    extra_tools: list[BaseTool] | None = [exec_tool] if exec_tool is not None else None
    guesser, simulator = _make_agents(
        api=api, model=model_name, guesser_system=guesser_system, sim_system=sim_system, extra_guesser_tools=extra_tools
    )

    result, turns, log_entries = run_game_loop(
        guesser=guesser, simulator=simulator, first_msg=first_msg, turn_limit=turn_limit
    )

    with calls_path.open("w") as f:
        for entry in log_entries:
            f.write(entry.model_dump_json() + "\n")

    summary = RunSummary(eval_name=name, framework="crewai", model=model_name, api=api, turns=turns, result=result)
    save_summary(summary=summary, summary_path=summary_path)
    return summary


async def _setup_and_run(loop: asyncio.AbstractEventLoop, ready: threading.Event, state: dict[str, Any]) -> None:
    """Enter async context managers for the MCP server+client on *loop*.

    Signals *ready* once the client is available in *state*, then waits for
    *state["done"]* to be set before tearing down.
    """
    async with scratch_exec_server() as server, Client(server) as mcp_client:
        state["mcp_client"] = mcp_client
        ready.set()
        # Block until the main thread signals we're done.
        done_event: asyncio.Event = state["done_event"]
        await done_event.wait()


def _run_with_exec(args: argparse.Namespace) -> None:
    """Set up an MCP exec bridge on a background event loop, then run the game."""
    # Background event loop for the async MCP server + client.
    bg_loop = asyncio.new_event_loop()
    ready = threading.Event()
    done_async = asyncio.Event()
    state: dict[str, Any] = {"done_event": done_async}

    def _run_bg() -> None:
        asyncio.set_event_loop(bg_loop)
        bg_loop.run_until_complete(_setup_and_run(bg_loop, ready, state))

    bg_thread = threading.Thread(target=_run_bg, daemon=True)
    bg_thread.start()
    ready.wait()

    try:
        exec_tool = ExecTool(mcp_client=state["mcp_client"], loop=bg_loop)
        _run_main(args, exec_tool=exec_tool)
    finally:
        bg_loop.call_soon_threadsafe(done_async.set)
        bg_thread.join(timeout=10)
        bg_loop.close()


def _run_main(args: argparse.Namespace, *, exec_tool: ExecTool | None = None) -> None:
    v = VARIANTS[args.variant]
    name = f"20q_{args.variant}"

    skill_text = load_skill_prompt()
    guesser_system = build_guesser_system(skill_text)
    sim_system = load_sim_prompt(secret=v.secret, turn_limit=v.turn_limit)
    first_msg = first_user_message(v.domain_description, v.turn_limit)
    output_dir = output_dir_from_args(args)

    logger.info("=" * 60)
    logger.info("  %s  |  %s  |  %s (crewai)", name, args.model, args.api)
    logger.info("=" * 60)

    summary = run_twenty_questions_crewai(
        name=name,
        api=args.api,
        model_name=args.model,
        guesser_system=guesser_system,
        sim_system=sim_system,
        first_msg=first_msg,
        turn_limit=v.turn_limit,
        output_dir=output_dir,
        exec_tool=exec_tool,
    )
    logger.info("%s", summary)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    p = argparse.ArgumentParser(description="Twenty Questions eval (CrewAI)")
    add_common_args(p)
    args = p.parse_args()
    resolve_args(args)

    _run_with_exec(args)


if __name__ == "__main__":
    main()
