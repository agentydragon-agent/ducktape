"""Shared eval harness for info-gathering skill.

Agent (uses skill) vs Simulator (holds ground truth). Provides:
- CLI utilities (add_common_args, model_from_args, etc.)
- Pydantic models for results and logging
- Helpers for loading the skill text

Uses the OpenAI Responses API via BoundOpenAIModel / RetryingOpenAIModel.
"""

import argparse
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from openai import AsyncOpenAI
from pydantic import BaseModel

from openai_utils.model import BoundOpenAIModel, OpenAIModelProto
from openai_utils.retry import RetryingOpenAIModel
from util.bazel.runfiles import get_required_path

logger = logging.getLogger(__name__)


# === Pydantic models ==========================================================


class LogEntry(BaseModel):
    timestamp: str
    eval_name: str
    player: Literal["agent", "simulator"]
    turn: int
    model: str
    content: str
    tool_calls: list[dict] = []
    stop_reason: str


class RunSummary(BaseModel):
    eval_name: str
    model: str
    turns: int
    result: BaseModel


# === Logging/saving helpers ===================================================


def save_results(*, name: str, log_entries: list[LogEntry], summary: RunSummary, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    prefix = output_dir / f"{name}_{ts}"

    calls_path = prefix.with_name(prefix.name + "_calls.jsonl")
    calls_path.write_text("".join(entry.model_dump_json() + "\n" for entry in log_entries))

    summary_path = prefix.with_name(prefix.name + "_summary.json")
    summary_path.write_text(summary.model_dump_json(indent=2))

    logger.info("Saved: %s_*", prefix)


# === CLI helpers ==============================================================

DEFAULT_MODEL = "gpt-oss:20b"

_SKILL_RLOCATION = "_main/skills/info_gathering/SKILL.md"


def load_skill() -> str:
    return get_required_path(_SKILL_RLOCATION).read_text()


def build_agent_system(skill_text: str, extra_system: str = "") -> str:
    parts = ["Follow this information-gathering skill throughout.\n\n<skill>\n" + skill_text + "\n</skill>"]
    if extra_system:
        parts.append("\n---\n\n" + extra_system)
    return "\n".join(parts)


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Model name (e.g. gpt-oss:20b)")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument(
        "--base-url", default="https://ollama.allegedly.works/v1", help="OpenAI-compatible Responses API base URL"
    )
    parser.add_argument("--api-key", default=None, help="API key")


def output_dir_from_args(args: argparse.Namespace) -> Path:
    d = Path(args.output_dir) if args.output_dir else Path("eval_results") / datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    d.mkdir(parents=True, exist_ok=True)
    return d


def model_from_args(args: argparse.Namespace) -> OpenAIModelProto:
    client = AsyncOpenAI(base_url=args.base_url, api_key=args.api_key or "unused")
    return RetryingOpenAIModel(base=BoundOpenAIModel(client=client, model=args.model))
