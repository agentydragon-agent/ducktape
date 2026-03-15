"""Shared eval harness for info-gathering skill.

Agent (uses skill) vs Simulator (holds ground truth). Provides:
- API helpers via LiteLLM (call_api, resolve_tool_calls)
- Conversation eval runner (run_conversation_eval)
- CLI utilities (add_common_args, load_skill, etc.)
- Pydantic models for results and logging

Supports any LiteLLM-compatible model string, e.g.:
  anthropic/claude-haiku-4-5-20251001
  openai/gpt-oss-20b-128k  (with --base-url for custom endpoints)
"""

import argparse
import contextlib
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import litellm
from pydantic import BaseModel

from util.bazel.runfiles import get_required_path

logger = logging.getLogger(__name__)

ToolHandler = Callable[[str, dict[str, Any]], dict[str, Any]]

# Suppress litellm's verbose logging by default
litellm.suppress_debug_info = True


# === Pydantic models ==========================================================


class Judged(BaseModel):
    """Result from simulator judgment or Python-side scoring."""

    outcome: Literal["correct", "incorrect", "partial", "timeout"]
    score: float = 0
    summary: str = ""


class EndGameInput(BaseModel):
    """Input schema for the end_game tool (simulator terminates the game)."""

    outcome: Literal["correct", "incorrect", "partial"]
    score: float
    summary: str


class Recommendation(BaseModel):
    title: str
    stars: int
    turn: int


class LogEntry(BaseModel):
    timestamp: str
    eval_name: str
    player: Literal["agent", "simulator"]
    turn: int
    model: str
    content: str
    reasoning_content: str | None = None
    tool_calls: list[dict[str, Any]] = []
    stop_reason: str
    usage: dict[str, Any]


class TokenTracker(BaseModel):
    model: str
    api_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    PRICING: dict[str, dict[str, float]] = {
        "anthropic/claude-haiku-4-5-20251001": {"input": 1.0, "output": 5.0},
        "anthropic/claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
        "anthropic/claude-opus-4-20250514": {"input": 15.0, "output": 75.0},
    }

    def add(self, usage: Any) -> None:
        self.input_tokens += usage.prompt_tokens or 0
        self.output_tokens += usage.completion_tokens or 0
        self.api_calls += 1

    @property
    def cost_usd(self) -> float:
        p = self.PRICING.get(self.model, {"input": 1.0, "output": 5.0})
        return (self.input_tokens * p["input"] + self.output_tokens * p["output"]) / 1_000_000


class RunSummary(BaseModel):
    eval_name: str
    model: str
    turns: int
    result: BaseModel
    recommendations: list[Recommendation] = []
    api_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    api_cost_usd: float = 0


# === Tool helpers ==============================================================


ToolParam = dict[str, Any]


def tool_def(name: str, description: str, input_model: type[BaseModel]) -> ToolParam:
    """Build an OpenAI-format tool definition from a Pydantic model."""
    schema = input_model.model_json_schema()
    # Remove $defs and other non-standard keys for OpenAI compatibility
    schema.pop("$defs", None)
    schema.pop("title", None)
    return {"type": "function", "function": {"name": name, "description": description, "parameters": schema}}


END_GAME_TOOL = tool_def("end_game", "End the game. Call when the agent states a final answer.", EndGameInput)


# === API helpers ==============================================================


def extract_text(response: Any) -> str:
    """Extract text content from a LiteLLM ModelResponse."""
    msg = response.choices[0].message
    return msg.content or ""


def extract_tool_calls(response: Any) -> list[Any]:
    """Extract tool calls from a LiteLLM ModelResponse."""
    msg = response.choices[0].message
    return msg.tool_calls or []


def call_api(
    *,
    messages: list[dict[str, Any]],
    system: str,
    model: str,
    tools: list[ToolParam] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
    max_tokens: int = 4096,
    thinking_budget: int | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> Any:
    """Call the LLM via LiteLLM.

    Works with any LiteLLM-supported model string (anthropic/..., openai/..., etc.).
    """
    # Prepend system message
    full_messages = [{"role": "system", "content": system}, *messages]

    kwargs: dict[str, Any] = {"model": model, "messages": full_messages}

    # Reasoning models (e.g. gpt-oss) need max_completion_tokens instead of max_tokens,
    # otherwise reasoning consumes the entire token budget leaving empty content.
    if model.startswith("anthropic/"):
        kwargs["max_tokens"] = max_tokens
    else:
        kwargs["max_completion_tokens"] = max_tokens

    if tools is not None:
        kwargs["tools"] = tools
    if tool_choice is not None:
        kwargs["tool_choice"] = tool_choice
    if base_url is not None:
        kwargs["api_base"] = base_url
    if api_key is not None:
        kwargs["api_key"] = api_key

    # Anthropic extended thinking
    if thinking_budget and model.startswith("anthropic/"):
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}

    return litellm.completion(**kwargs)


def resolve_tool_calls(
    *,
    response: Any,
    messages: list[dict[str, Any]],
    system: str,
    model: str,
    tools: list[ToolParam],
    handler: ToolHandler,
    max_tokens: int = 4096,
    thinking_budget: int | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> tuple[Any, list[dict[str, Any]], list[Any]]:
    """Keep calling API until no more tool_use stops. Returns final response."""
    usages: list[Any] = []
    messages = list(messages)

    while response.choices[0].finish_reason == "tool_use" or (
        response.choices[0].finish_reason == "stop" and extract_tool_calls(response)
    ):
        tcs = extract_tool_calls(response)
        if not tcs:
            break

        # Append assistant message with tool calls
        assistant_msg: dict[str, Any] = {"role": "assistant", "content": extract_text(response) or None}
        assistant_msg["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in tcs
        ]
        messages.append(assistant_msg)

        # Build tool result messages
        for tc in tcs:
            args = json.loads(tc.function.arguments)
            result = handler(tc.function.name, args)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result) if isinstance(result, dict) else str(result),
                }
            )

        response = call_api(
            messages=messages,
            system=system,
            model=model,
            tools=tools,
            max_tokens=max_tokens,
            thinking_budget=thinking_budget,
            base_url=base_url,
            api_key=api_key,
        )
        usages.append(response.usage)

    return response, messages, usages


# === Logging/saving helpers ===================================================


def log_response(
    log_entries: list[LogEntry],
    *,
    name: str,
    player: Literal["agent", "simulator"],
    turn: int,
    model: str,
    response: Any,
) -> None:
    msg = response.choices[0].message
    tool_calls_data = []
    if msg.tool_calls:
        tool_calls_data = [
            {"id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments} for tc in msg.tool_calls
        ]

    # LiteLLM's Message type declares reasoning_content as Optional[str],
    # but deletes the attribute when None for OpenAI spec compatibility.
    reasoning: str | None = None
    with contextlib.suppress(AttributeError):
        reasoning = msg.reasoning_content

    log_entries.append(
        LogEntry(
            timestamp=datetime.now(UTC).isoformat(),
            eval_name=name,
            player=player,
            turn=turn,
            model=model,
            content=msg.content or "",
            reasoning_content=reasoning,
            tool_calls=tool_calls_data,
            stop_reason=response.choices[0].finish_reason or "",
            usage=response.usage.model_dump() if hasattr(response.usage, "model_dump") else dict(response.usage),
        )
    )


def save_results(*, name: str, log_entries: list[LogEntry], summary: RunSummary, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    prefix = output_dir / f"{name}_{ts}"

    calls_path = Path(f"{prefix}_calls.jsonl")
    calls_path.write_text("".join(entry.model_dump_json() + "\n" for entry in log_entries))

    summary_path = Path(f"{prefix}_summary.json")
    summary_path.write_text(summary.model_dump_json(indent=2))

    logger.info("Saved: %s_*", prefix)


# === CLI helpers ==============================================================

DEFAULT_MODEL = "anthropic/claude-haiku-4-5-20251001"
DEFAULT_THINKING = 5000

_SKILL_RLOCATION = "_main/nix/home/skills/info_gathering/SKILL.md"


def load_skill() -> str:
    return get_required_path(_SKILL_RLOCATION).read_text()


def build_agent_system(skill_text: str, extra_system: str = "") -> str:
    parts = ["Follow this information-gathering skill throughout.\n\n<skill>\n" + skill_text + "\n</skill>"]
    if extra_system:
        parts.append("\n---\n\n" + extra_system)
    return "\n".join(parts)


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="LiteLLM model string, e.g. anthropic/claude-haiku-4-5-20251001 or openai/gpt-oss-20b-128k",
    )
    parser.add_argument(
        "--thinking-budget", type=int, default=DEFAULT_THINKING, help="0 to disable (only for anthropic/ models)"
    )
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--base-url", default=None, help="Custom API base URL (e.g. https://ollama.allegedly.works/v1)")
    parser.add_argument("--api-key", default=None, help="API key (reads from provider env var by default)")


def thinking_from_args(args: argparse.Namespace) -> int | None:
    return args.thinking_budget if args.thinking_budget > 0 else None


def output_dir_from_args(args: argparse.Namespace) -> Path:
    d = Path(args.output_dir) if args.output_dir else Path("eval_results") / datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    d.mkdir(parents=True, exist_ok=True)
    return d


# === Conversation eval runner =================================================


def run_conversation_eval(
    *,
    name: str,
    model: str,
    agent_system: str,
    first_user_message: str,
    sim_system: str,
    sim_tools: list[ToolParam],
    turn_limit: int = 20,
    thinking_budget: int | None = None,
    output_dir: Path,
    base_url: str | None = None,
    api_key: str | None = None,
) -> RunSummary:
    """Run a conversation eval: agent and simulator exchange text.

    Simulator may call tools (end_game to finish, others passed through).
    Agent has no tools in this pattern.
    """
    tracker = TokenTracker(model=model)
    log_entries: list[LogEntry] = []
    result: Judged | None = None

    agent_messages: list[dict[str, Any]] = [{"role": "user", "content": first_user_message}]
    sim_messages: list[dict[str, Any]] = []

    def handle_sim_tool(tool_name: str, inp: dict[str, Any]) -> dict[str, Any]:
        nonlocal result
        if tool_name == "end_game":
            parsed = EndGameInput.model_validate(inp)
            result = Judged(outcome=parsed.outcome, score=parsed.score, summary=parsed.summary)
            return {"status": "game_ended"}
        return inp

    for turn in range(1, turn_limit + 1):
        logger.info("Turn %d...", turn)

        # Agent turn (no tools)
        agent_resp = call_api(
            messages=agent_messages,
            system=agent_system,
            model=model,
            thinking_budget=thinking_budget,
            base_url=base_url,
            api_key=api_key,
        )
        tracker.add(agent_resp.usage)
        log_response(log_entries, name=name, player="agent", turn=turn, model=model, response=agent_resp)
        agent_messages.append({"role": "assistant", "content": extract_text(agent_resp)})

        agent_text = extract_text(agent_resp).strip()
        if not agent_text:
            continue

        # Simulator turn (with tools)
        sim_messages.append({"role": "user", "content": agent_text})
        sim_resp = call_api(
            messages=sim_messages,
            system=sim_system,
            model=model,
            tools=sim_tools,
            thinking_budget=thinking_budget,
            base_url=base_url,
            api_key=api_key,
        )
        tracker.add(sim_resp.usage)
        log_response(log_entries, name=name, player="simulator", turn=turn, model=model, response=sim_resp)

        if extract_tool_calls(sim_resp):
            sim_resp, sim_messages, usages = resolve_tool_calls(
                response=sim_resp,
                messages=sim_messages,
                system=sim_system,
                model=model,
                tools=sim_tools,
                handler=handle_sim_tool,
                thinking_budget=thinking_budget,
                base_url=base_url,
                api_key=api_key,
            )
            for u in usages:
                tracker.add(u)
            log_response(log_entries, name=name, player="simulator", turn=turn, model=model, response=sim_resp)

        sim_messages.append({"role": "assistant", "content": extract_text(sim_resp)})
        sim_text = extract_text(sim_resp).strip()
        agent_messages.append({"role": "user", "content": sim_text})

        if result:
            break
    else:
        result = Judged(outcome="timeout", summary=f"Hit {turn_limit} turn limit")

    summary = RunSummary(
        eval_name=name,
        model=model,
        turns=turn,
        result=result,
        api_calls=tracker.api_calls,
        input_tokens=tracker.input_tokens,
        output_tokens=tracker.output_tokens,
        api_cost_usd=round(tracker.cost_usd, 4),
    )
    save_results(name=name, log_entries=log_entries, summary=summary, output_dir=output_dir)
    return summary
