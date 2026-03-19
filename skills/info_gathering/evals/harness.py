"""Shared eval harness for info-gathering skill.

Agent (uses skill) vs Simulator (holds ground truth). Provides:
- LLMClient wrapping OpenAI SDK / LiteLLM (call, resolve_tool_calls)
- CLI utilities (add_common_args, load_skill, etc.)
- Pydantic models for results and logging

Uses openai SDK directly for OpenAI-compatible endpoints (Ollama, LiteLLM proxy).
Uses litellm for Anthropic models (which need provider-specific params like thinking).
"""

import argparse
import contextlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

import litellm
from openai import AsyncOpenAI
from pydantic import BaseModel

from agent_core.tool_provider import ToolProvider
from openai_utils.json_schema import openai_json_schema
from skills.info_gathering.evals.litellm_tool_provider import ToolParam, tool_params_from_provider, tool_result_content
from util.bazel.runfiles import get_required_path

logger = logging.getLogger(__name__)

# Suppress litellm's verbose logging by default
litellm.suppress_debug_info = True


# === Pydantic models ==========================================================


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
    raw_response: dict[str, Any]


class RunSummary(BaseModel):
    eval_name: str
    model: str
    turns: int
    result: BaseModel


# === Tool helpers ==============================================================


def tool_def(name: str, description: str, input_model: type[BaseModel]) -> ToolParam:
    """Build an OpenAI-format tool definition from a Pydantic model."""
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": openai_json_schema(input_model)},
    }


# === LLM client ===============================================================


def extract_tool_calls(response: Any) -> list[Any]:
    """Extract tool calls from an API response (OpenAI SDK or LiteLLM)."""
    msg = response.choices[0].message
    return msg.tool_calls or []


def _has_tool_calls(response: Any) -> bool:
    """Check if response indicates the model wants to call tools."""
    finish = response.choices[0].finish_reason
    # "tool_use" = Anthropic, "tool_calls" = OpenAI/Ollama, "stop" = some providers
    return finish in ("tool_use", "tool_calls") or (finish == "stop" and bool(extract_tool_calls(response)))


class LLMClient:
    """Wraps OpenAI SDK / LiteLLM with shared config (model, base_url, api_key, thinking).

    For anthropic/ models: uses litellm (handles thinking budgets, Anthropic-specific params).
    For all other models: uses openai SDK directly, bypassing litellm's parameter filtering.
    """

    def __init__(
        self, *, model: str, thinking_budget: int | None = None, base_url: str | None = None, api_key: str | None = None
    ) -> None:
        self.model = model
        self.thinking_budget = thinking_budget
        self.base_url = base_url
        self.api_key = api_key

        if not model.startswith("anthropic/"):
            self._openai_client = AsyncOpenAI(base_url=base_url, api_key=api_key or "unused")

    async def call(
        self,
        *,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[ToolParam] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        max_tokens: int = 4096,
    ) -> Any:
        """Call the LLM."""
        full_messages: list[dict[str, Any]] = [{"role": "system", "content": system}, *messages]

        if self.model.startswith("anthropic/"):
            return await self._call_anthropic(
                full_messages=full_messages, tools=tools, tool_choice=tool_choice, max_tokens=max_tokens
            )

        # OpenAI-compatible path (Ollama, LiteLLM proxy, OpenAI, etc.)
        model_name = self.model.removeprefix("openai/")
        kwargs: dict[str, Any] = {}
        if tools:
            kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice

        return await self._openai_client.chat.completions.create(
            model=model_name, messages=cast(Any, full_messages), max_completion_tokens=max_tokens, **kwargs
        )

    async def _call_anthropic(
        self,
        *,
        full_messages: list[dict[str, Any]],
        tools: list[ToolParam] | None,
        tool_choice: str | dict[str, Any] | None,
        max_tokens: int,
    ) -> Any:
        """Call Anthropic models via litellm (handles thinking budgets, etc.)."""
        thinking = None
        if self.thinking_budget:
            thinking = {"type": "enabled", "budget_tokens": self.thinking_budget}

        return await litellm.acompletion(
            model=self.model,
            messages=full_messages,
            tools=tools,
            tool_choice=tool_choice,
            api_base=self.base_url,
            api_key=self.api_key,
            thinking=thinking,
            max_tokens=max_tokens,
        )

    async def resolve_tool_calls(
        self,
        *,
        response: Any,
        messages: list[dict[str, Any]],
        system: str,
        provider: ToolProvider,
        max_tokens: int = 4096,
    ) -> tuple[Any, list[dict[str, Any]], list[Any]]:
        """Keep calling API until no more tool calls. Returns final response."""
        tools = await tool_params_from_provider(provider)
        usages: list[Any] = []
        messages = list(messages)

        while _has_tool_calls(response):
            tcs = extract_tool_calls(response)
            if not tcs:
                break

            # Append assistant message with tool calls
            messages.append(_serialize_message(response.choices[0].message))

            # Build tool result messages
            for tc in tcs:
                args = json.loads(tc.function.arguments)
                result = await provider.call_tool(tc.function.name, args)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": tool_result_content(result)})

            response = await self.call(messages=messages, system=system, tools=tools, max_tokens=max_tokens)
            usages.append(response.usage)

        return response, messages, usages


# === Logging/saving helpers ===================================================


def _serialize_message(msg: Any) -> dict[str, Any]:
    """Serialize an API message to a typed dict for conversation history."""
    result: dict[str, Any] = {"role": "assistant", "content": msg.content}
    if msg.tool_calls:
        result["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in msg.tool_calls
        ]
    return result


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

    # reasoning_content may not exist on all response types
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
            raw_response=response.model_dump(),
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

_SKILL_RLOCATION = "_main/skills/info_gathering/SKILL.md"


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
        help="Model string, e.g. anthropic/claude-haiku-4-5-20251001 or openai/gpt-oss:20b",
    )
    parser.add_argument(
        "--thinking-budget", type=int, default=DEFAULT_THINKING, help="0 to disable (only for anthropic/ models)"
    )
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--base-url", default=None, help="Custom API base URL (e.g. https://ollama.allegedly.works)")
    parser.add_argument("--api-key", default=None, help="API key (reads from provider env var by default)")


def thinking_from_args(args: argparse.Namespace) -> int | None:
    return args.thinking_budget if args.thinking_budget > 0 else None


def output_dir_from_args(args: argparse.Namespace) -> Path:
    d = Path(args.output_dir) if args.output_dir else Path("eval_results") / datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    d.mkdir(parents=True, exist_ok=True)
    return d


def client_from_args(args: argparse.Namespace) -> LLMClient:
    return LLMClient(
        model=args.model, thinking_budget=thinking_from_args(args), base_url=args.base_url, api_key=args.api_key
    )
