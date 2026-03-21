"""Twenty Questions eval using LangGraph.

Usage:
  bazel run //skills/info_gathering/evals/twenty_questions/x/langgraph:twenty_questions_bin -- \
    --variant states --api openai --model gpt-4o-mini
"""

import argparse
import asyncio
import contextlib
import logging
import operator
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, TypedDict

from fastmcp.client import Client
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import (
    BaseTool,
    tool as langchain_tool,  # renamed to avoid collision with local tool definitions
)
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.types import Command
from pydantic import BaseModel, Field

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


# -- Tools for the simulator LLM --


class AnswerInput(BaseModel):
    response: Literal["yes", "no", "sort_of"] = Field(description="Answer to the player's yes/no question")


@langchain_tool(args_schema=AnswerInput)
def answer(response: str) -> str:
    """Answer the player's yes/no question."""
    return response


@langchain_tool
def correct_answer() -> str:
    """The player correctly guessed the secret."""
    return "correct"


SIM_TOOLS = [answer, correct_answer]


# -- State --


class GameState(TypedDict):
    """Shared state flowing through the Twenty Questions graph.

    Message lists use the add_messages reducer so nodes can append without
    manually copying the full list. log_entries uses operator.add to
    accumulate entries from both players. Scalar fields (turn, result,
    last_question) use default overwrite semantics.
    """

    guesser_messages: Annotated[list[BaseMessage], add_messages]
    simulator_messages: Annotated[list[BaseMessage], add_messages]
    turn: int
    turn_limit: int
    result: Result | None
    last_question: str | None
    log_entries: Annotated[list[LogEntry], operator.add]


# -- Helpers --


def _make_chat_model(api: str, model: str) -> BaseChatModel:
    # Conditional imports: only load the provider package actually requested,
    # avoiding heavyweight transitive deps from the unused provider.
    if api == "openai":
        return ChatOpenAI(model=model)
    return ChatAnthropic(model=model)


# -- Graph construction --


def build_graph(
    *, guesser_model: BaseChatModel, simulator_model: BaseChatModel, exec_tool: BaseTool | None = None
) -> StateGraph[GameState, None, GameState, GameState]:
    """Build the LangGraph state graph for Twenty Questions."""
    sim_with_tools = simulator_model.bind_tools(SIM_TOOLS, tool_choice="required")

    # Bind exec tool to guesser if provided, so it can run commands before asking.
    effective_guesser = guesser_model.bind_tools([exec_tool]) if exec_tool else guesser_model

    async def guesser_node(state: GameState) -> Command[Literal["exec_tools", "simulator_llm"]]:
        response: AIMessage = await effective_guesser.ainvoke(state["guesser_messages"])
        text = str(response.text).strip()

        # If the model made tool calls, route to exec_tools node.
        # The exec tool is the only tool bound to the guesser.
        tool_calls = response.tool_calls or []
        if tool_calls:
            return Command(update={"guesser_messages": [response]}, goto="exec_tools")

        entry = LogEntry(timestamp=datetime.now(UTC), player="guesser", content=text)
        return Command(
            update={"guesser_messages": [response], "last_question": text, "log_entries": [entry]}, goto="simulator_llm"
        )

    async def simulator_llm_node(state: GameState) -> dict[str, list[BaseMessage]]:
        """Invoke the simulator LLM and append the question + response."""
        question = state["last_question"] or ""
        question_msg = HumanMessage(content=question)
        response: AIMessage = await sim_with_tools.ainvoke(state["simulator_messages"] + [question_msg])
        return {"simulator_messages": [question_msg, response]}

    # ToolNode executes simulator tools (answer / correct_answer) and appends
    # proper ToolMessages to simulator_messages.
    sim_tool_node = ToolNode(SIM_TOOLS, messages_key="simulator_messages")

    async def simulator_route_node(state: GameState) -> Command[Literal["guesser", "__end__"]]:
        """Inspect simulator tool calls and determine game outcome."""
        # Find the most recent AIMessage with tool calls — the structured
        # decision is in the call arguments, not in the ToolMessage results.
        last_ai: AIMessage | None = None
        for msg in reversed(state["simulator_messages"]):
            if isinstance(msg, AIMessage) and msg.tool_calls:
                last_ai = msg
                break
        tool_calls = last_ai.tool_calls if last_ai else []
        tool_call_dicts = [{"name": tc["name"], "args": tc["args"]} for tc in tool_calls]

        result: Result | None = None
        sim_reply = ""
        for tc in tool_calls:
            if tc["name"] == "correct_answer":
                result = Correct(turns=state["turn"])
                break
            if tc["name"] == "answer":
                sim_reply = tc["args"]["response"]

        new_turn = state["turn"] + 1
        if result is None and new_turn > state["turn_limit"]:
            result = Timeout(limit=state["turn_limit"])

        entry = LogEntry(timestamp=datetime.now(UTC), player="simulator", content=sim_reply, tool_calls=tool_call_dicts)

        guesser_feedback: list[BaseMessage] = []
        if result is None and sim_reply:
            guesser_feedback = [HumanMessage(content=sim_reply)]

        game_over = result is not None
        return Command(
            update={"turn": new_turn, "result": result, "log_entries": [entry], "guesser_messages": guesser_feedback},
            goto=END if game_over else "guesser",  # type: ignore[arg-type]
        )

    exec_tools_list = [exec_tool] if exec_tool else []
    exec_tool_node = ToolNode(exec_tools_list, messages_key="guesser_messages")

    graph = StateGraph(GameState, input_schema=GameState, output_schema=GameState)
    graph.add_node("guesser", guesser_node)
    graph.add_node("exec_tools", exec_tool_node)
    graph.add_node("simulator_llm", simulator_llm_node)
    graph.add_node("simulator_tools", sim_tool_node)
    graph.add_node("simulator_route", simulator_route_node)
    graph.add_edge(START, "guesser")
    graph.add_edge("exec_tools", "guesser")
    graph.add_edge("simulator_llm", "simulator_tools")
    graph.add_edge("simulator_tools", "simulator_route")

    return graph


async def run_twenty_questions_langgraph(
    *,
    name: str,
    api: str,
    model_name: str,
    guesser_system: str,
    sim_system: str,
    first_message: str,
    turn_limit: int,
    output_dir: Path,
    exec_server: ContainerExecServer | None = None,
) -> RunSummary:
    """Run a full Twenty Questions game with LangGraph and return a summary."""
    calls_path, summary_path = run_output_paths(name, output_dir)

    guesser_model = _make_chat_model(api, model_name)
    simulator_model = _make_chat_model(api, model_name)

    async with contextlib.AsyncExitStack() as stack:
        exec_tool: BaseTool | None = None
        if exec_server is not None:
            mcp_client = await stack.enter_async_context(Client(exec_server))
            tools = await load_mcp_tools(mcp_client.session)
            exec_tool = next(t for t in tools if t.name == "exec")

        graph = build_graph(guesser_model=guesser_model, simulator_model=simulator_model, exec_tool=exec_tool)
        app = graph.compile()

        initial_state: GameState = {
            "guesser_messages": [SystemMessage(content=guesser_system), HumanMessage(content=first_message)],
            "simulator_messages": [SystemMessage(content=sim_system)],
            "turn": 1,
            "turn_limit": turn_limit,
            "result": None,
            "last_question": None,
            "log_entries": [],
        }

        final_state = await app.ainvoke(initial_state)

    result: Result = final_state["result"]
    assert result is not None, "Graph terminated without setting result"
    log_entries: list[LogEntry] = final_state["log_entries"]
    turns = final_state["turn"] - 1

    with calls_path.open("w") as f:
        for entry in log_entries:
            f.write(entry.model_dump_json() + "\n")

    summary = RunSummary(eval_name=name, framework="langgraph", model=model_name, api=api, turns=turns, result=result)
    save_summary(summary=summary, summary_path=summary_path)
    return summary


async def _async_main(args: argparse.Namespace) -> None:
    v = VARIANTS[args.variant]
    name = f"20q_{args.variant}"

    skill_text = load_skill_prompt()
    guesser_system = build_guesser_system(skill_text)
    sim_system = load_sim_prompt(secret=v.secret, turn_limit=v.turn_limit)
    first_msg = first_user_message(v.domain_description, v.turn_limit)
    output_dir = output_dir_from_args(args)

    logger.info("=" * 60)
    logger.info("  %s  |  %s  |  %s (langgraph)", name, args.model, args.api)
    logger.info("=" * 60)

    async with scratch_exec_server() as exec_server:
        summary = await run_twenty_questions_langgraph(
            name=name,
            api=args.api,
            model_name=args.model,
            guesser_system=guesser_system,
            sim_system=sim_system,
            first_message=first_msg,
            turn_limit=v.turn_limit,
            output_dir=output_dir,
            exec_server=exec_server,
        )
    logger.info("%s", summary)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    p = argparse.ArgumentParser(description="Twenty Questions eval (LangGraph)")
    add_common_args(p)
    args = p.parse_args()
    resolve_args(args)

    asyncio.run(_async_main(args))


if __name__ == "__main__":
    main()
