"""Twenty Questions eval variants.

Usage:
  bazel run //nix/home/skills/info_gathering/evals/twenty_questions:twenty_questions_bin -- --variant states
  bazel run //nix/home/skills/info_gathering/evals/twenty_questions:twenty_questions_bin -- --variant states --model openai/gpt-oss:20b --base-url https://ollama-api.allegedly.works --thinking-budget 0
"""

import argparse
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from nix.home.skills.info_gathering.evals.harness import (
    LLMClient,
    LogEntry,
    RunSummary,
    TokenTracker,
    ToolParam,
    _serialize_message,
    add_common_args,
    build_agent_system,
    client_from_args,
    extract_tool_calls,
    load_skill,
    log_response,
    output_dir_from_args,
    save_results,
    tool_def,
)
from util.bazel.runfiles import get_required_path

logger = logging.getLogger(__name__)

_SIM_RLOCATION = "_main/nix/home/skills/info_gathering/evals/twenty_questions/sim.txt"


class Correct(BaseModel):
    turns: int


class Timeout(BaseModel):
    limit: int


class AnswerInput(BaseModel):
    response: Literal["yes", "no", "sort_of"]


class CorrectAnswerInput(BaseModel):
    """The player correctly guessed the secret."""


ANSWER_TOOL = tool_def("answer", "Answer the player's yes/no question.", AnswerInput)
CORRECT_ANSWER_TOOL = tool_def("correct_answer", "The player correctly guessed the secret.", CorrectAnswerInput)

SIM_TOOLS: list[ToolParam] = [ANSWER_TOOL, CORRECT_ANSWER_TOOL]


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


def _parse_sim_action(response: Any) -> tuple[str, str | None] | None:
    """Parse the simulator's tool call into (tool_name, answer_value).

    Returns None if no valid tool call found.
    """
    tcs = extract_tool_calls(response)
    if len(tcs) != 1:
        return None
    tc = tcs[0]
    if tc.function.name == "correct_answer":
        return ("correct_answer", None)
    if tc.function.name == "answer":
        args = json.loads(tc.function.arguments)
        validated = AnswerInput.model_validate(args)
        return ("answer", validated.response)
    return None


def run_twenty_questions(
    *,
    name: str,
    client: LLMClient,
    agent_system: str,
    first_user_message: str,
    sim_system: str,
    turn_limit: int = 20,
    output_dir: Path,
) -> RunSummary:
    """Run a 20 Questions eval.

    Agent asks questions (text only). Simulator answers via tool calls.
    Game ends when sim calls correct_answer or turns run out.
    """
    tracker = TokenTracker(model=client.model)
    log_entries: list[LogEntry] = []

    agent_messages: list[dict[str, Any]] = [{"role": "user", "content": first_user_message}]
    sim_messages: list[dict[str, Any]] = []
    last_tc_id: str | None = None
    result: Correct | Timeout

    for turn in range(1, turn_limit + 1):
        logger.info("Turn %d...", turn)

        # Agent turn (no tools)
        agent_resp = client.call(messages=agent_messages, system=agent_system)
        tracker.add(agent_resp.usage)
        log_response(log_entries, name=name, player="agent", turn=turn, model=client.model, response=agent_resp)

        agent_msg = _serialize_message(agent_resp.choices[0].message)
        agent_messages.append(agent_msg)

        agent_text = (agent_msg["content"] or "").strip()
        if not agent_text:
            continue

        # Sim turn — provide tool result from previous call if needed
        if last_tc_id:
            sim_messages.append({"role": "tool", "tool_call_id": last_tc_id, "content": "ok"})
        last_tc_id = None

        sim_messages.append({"role": "user", "content": agent_text})

        sim_resp = client.call(messages=sim_messages, system=sim_system, tools=SIM_TOOLS, tool_choice="auto")
        tracker.add(sim_resp.usage)
        log_response(log_entries, name=name, player="simulator", turn=turn, model=client.model, response=sim_resp)

        # Append assistant message with tool calls for conversation history
        sim_msg = _serialize_message(sim_resp.choices[0].message)
        sim_messages.append(sim_msg)

        action = _parse_sim_action(sim_resp)
        if action is None:
            logger.warning("Turn %d: could not parse simulator action", turn)
            agent_messages.append({"role": "user", "content": "(no response)"})
            continue

        tool_name, answer = action

        if tool_name == "correct_answer":
            result = Correct(turns=turn)
            break

        # answer action
        assert answer is not None
        tcs = extract_tool_calls(sim_resp)
        if tcs:
            last_tc_id = tcs[0].id
        agent_messages.append({"role": "user", "content": answer})
    else:
        result = Timeout(limit=turn_limit)

    summary = RunSummary(
        eval_name=name,
        model=client.model,
        turns=turn,
        result=result,
        api_calls=tracker.api_calls,
        input_tokens=tracker.input_tokens,
        output_tokens=tracker.output_tokens,
        api_cost_usd=round(tracker.cost_usd, 4),
    )
    save_results(name=name, log_entries=log_entries, summary=summary, output_dir=output_dir)
    return summary


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    p = argparse.ArgumentParser(description="Twenty Questions eval")
    add_common_args(p)
    p.add_argument("--variant", choices=list(VARIANTS), required=True)
    args = p.parse_args()

    v = VARIANTS[args.variant]
    name = f"20q_{args.variant}"

    skill_text = load_skill()
    agent_system = build_agent_system(skill_text)
    client = client_from_args(args)
    output_dir = output_dir_from_args(args)

    sim_template = get_required_path(_SIM_RLOCATION).read_text()
    sim_system = sim_template.format(secret=v.secret, turn_limit=v.turn_limit)

    first_user_message = (
        f"Play 20 Questions. I'm thinking of {v.domain_description}. "
        f"You have {v.turn_limit} yes/no questions. "
        "When confident, state: 'My answer is: [X]'."
    )

    logger.info("=" * 60)
    logger.info("  %s  |  %s  |  thinking=%s", name, client.model, client.thinking_budget or "off")
    logger.info("=" * 60)

    summary = run_twenty_questions(
        name=name,
        client=client,
        agent_system=agent_system,
        first_user_message=first_user_message,
        sim_system=sim_system,
        turn_limit=v.turn_limit,
        output_dir=output_dir,
    )
    logger.info("%s", summary)


if __name__ == "__main__":
    main()
