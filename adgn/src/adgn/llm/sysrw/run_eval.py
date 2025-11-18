import argparse
import asyncio
from collections.abc import Iterable
from contextlib import suppress
from datetime import datetime
from importlib import resources
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, cast

from jinja2 import Environment, FileSystemLoader, select_autoescape
from openai import AsyncOpenAI
from openai.types.chat import (
    ChatCompletionAssistantMessageParam,
    ChatCompletionMessageParam,
    ChatCompletionMessageToolCallParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionToolMessageParam,
    ChatCompletionUserMessageParam,
)
from openai.types.responses import Response, ResponseFunctionToolCall, ResponseOutputMessage
from pydantic import BaseModel, TypeAdapter
import tiktoken

from adgn.llm.anthropic.types import Message as AnthropicMessage, MessageRole as AnthropicMessageRole
from adgn.openai_utils.client_factory import get_async_openai
from adgn.openai_utils.retry import chat_create_with_retries, responses_create_with_retries

from .constants import TOOLS_HEADER
from .openai_typing import (
    MessageRole,
    ResponseContentPart,
    chat_param_message_content_as_text,
    chat_param_message_role,
    chat_param_message_tool_calls,
    dump_chat_messages,
    dump_response_messages,
    iter_resolved_text,
    parse_chat_messages,
    parse_response,
    parse_response_messages,
    parse_tools_list,
    response_message_content_as_text,
    response_message_role,
)
from .prompts import build_grader_prompt
from .schemas import (
    CCRSample,
    ChatAssistantMessage,
    CrushSample,
    EvalGradeRecord,
    EvalSampleRecord,
    Grade,
    Request,
    ResponsesAssistantMessage,
    Sample,
)
from .templates import validate_template_file
from .translation import anthropic_messages_to_standard, anthropic_to_chat_messages, anthropic_to_responses_input


# Config
DEFAULT_DATASET_PATH = Path(__file__).parent / "data" / "dataset.jsonl"
DEFAULT_BASE = Path(__file__).parent / "runs"
MAX_INPUT_TOKENS = 272_000
MAX_TOTAL_TOKENS = 400_000
PER_OUTPUT_CAP = 128_000
SAFETY_TOKENS = 1_024
TARGET_PREFIX_TOKENS = 200_000  # budget for prefix JSON inside grader prompt


# Models
SAMPLER_MODEL = "gpt-5"
GRADER_MODEL = "gpt-5"

# Paths
REWRITE_APPLY = resources.files("adgn.llm.sysrw").joinpath("js/system_rewrite_apply.js")


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--template",
        required=True,
        help="Path to system prompt template file with mustache placeholders: {{toolsBlob}}, {{envGitBlobs}}, {{modelLine}}, {{mcpSection}}",
    )
    ap.add_argument(
        "--dataset",
        action="append",
        required=False,
        help=(
            "Dataset JSONL path; can be repeated to mix CCR and Crush samples in one run. "
            "Defaults to ./data/dataset.jsonl if omitted."
        ),
    )
    ap.add_argument(
        "--out-dir",
        required=False,
        help=(
            "Output directory. If provided, results are written directly here (no nesting). "
            "If omitted, writes to runs/<ts> or runs/baseline-<ts> (for current_effective_template.txt)."
        ),
    )
    ap.add_argument("--n", type=int, default=None, help="Limit number of samples to process")
    ap.add_argument("--concurrency", type=int, default=32, help="Number of samples to run in parallel")
    return ap.parse_args()


async def read_dataset(dataset_path: Path) -> list[Sample]:
    items: list[Sample] = []
    with dataset_path.open("r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            # Support both CCR (anthropic_request) and Crush (oai_request) entries
            if "anthropic_request" in rec:
                items.append(CCRSample.model_validate(rec))
                continue
            if "oai_request" in rec:
                items.append(CrushSample.model_validate(rec))
                continue
    return items


# --- OpenAI client ---


def estimate_tokens(text: str) -> int:
    enc = tiktoken.get_encoding("cl100k_base")
    # Encode special-token-looking sequences as plain text (no ValueError)
    return len(enc.encode(text, disallowed_special=()))


def tokens_for_chat_messages(msgs: Any) -> int:
    if (messages := parse_chat_messages(msgs)) is None:
        return 0
    parts: list[str] = []
    for message in messages:
        parts.append(chat_param_message_role(message))
        if text := chat_param_message_content_as_text(message):
            parts.append(text)
        if tool_calls := chat_param_message_tool_calls(message):
            for call in tool_calls:
                if args := call["function"]["arguments"]:
                    parts.append(args)
    return estimate_tokens("\n".join(parts))


def flatten_system_string(sys: Any) -> str:
    if isinstance(sys, str):
        return sys
    if isinstance(sys, list):
        try:
            parts = TypeAdapter(list[ResponseContentPart]).validate_python(sys)
            return "\n\n".join(iter_resolved_text(parts))
        except Exception:
            pass
    return ""


def rewrite_system_with_template(system_text: str, template_path: Path) -> str:
    """Rewrite the system prompt via Node apply script.
    Fails clearly if Node.js is not available or the script errors out.
    """
    try:
        # Pass shared TOOLS_HEADER into the JS env to avoid magic strings
        env = {**os.environ, "TOOLS_HEADER": TOOLS_HEADER}
        proc = subprocess.run(
            ["node", str(REWRITE_APPLY), str(template_path)],
            input=system_text.encode("utf-8"),
            capture_output=True,
            check=False,
            timeout=60,
            env=env,
        )
    except FileNotFoundError as e:
        raise RuntimeError(
            "Node.js ('node') not found in PATH; install Node or adjust PATH to use system rewrite"
        ) from e
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr.decode("utf-8", errors="ignore"))
        raise RuntimeError(f"system rewrite failed with code {proc.returncode}")
    return proc.stdout.decode("utf-8")


ENV_INTRO = "Here is useful information about the environment you are running in:"
MODEL_PREFIX = "You are powered by the model"
MCP_HEADER = "# MCP Server Instructions"


def index_of_last_assistant_before_final(msgs: list[ChatCompletionMessageParam]) -> int | None:
    """Find index of last assistant message before the final message."""
    for i in range(len(msgs) - 2, -1, -1):
        if chat_param_message_role(msgs[i]) == MessageRole.ASSISTANT:
            return i
    return None


def index_of_last_assistant_in_anthropic_messages(messages: list[AnthropicMessage]) -> int | None:
    """Find index of last assistant message before the final message."""
    for i in range(len(messages) - 2, -1, -1):
        if messages[i].role == AnthropicMessageRole.ASSISTANT:
            return i
    return None


def convert_responses_tools_to_chat_functions(tools_val: Any) -> list[dict[str, Any]] | None:
    tools = parse_tools_list(tools_val)
    if not tools:
        return None
    normalized: list[dict[str, Any]] = []
    for tool in tools:
        payload = tool.model_dump(mode="json", exclude_none=True) if isinstance(tool, BaseModel) else dict(tool)
        normalized.append(payload)
    return normalized


GRADE_TOOL = {
    "type": "function",
    "name": "grade",
    "description": "Return a 1-5 score and a short rationale.",
    "parameters": {
        "type": "object",
        "properties": {"score": {"type": "integer", "minimum": 1, "maximum": 5}, "rationale": {"type": "string"}},
        "required": ["score", "rationale"],
        "additionalProperties": False,
    },
    "strict": True,
}


def parse_grade_from_responses(response: Response) -> Grade:
    """Parse grade from OpenAI Responses API output.

    Extracts the 'grade' tool call from the response output and validates it as a Grade model.
    """
    if not response.output:
        raise RuntimeError("No output in responses")

    for item in response.output:
        if isinstance(item, ResponseFunctionToolCall) and item.name == "grade":
            args = item.arguments
            if isinstance(args, str):
                return Grade.model_validate_json(args)
            return Grade.model_validate(args or {})
    raise RuntimeError("No grade tool call in responses output")


async def run_eval(
    template_path: Path,
    dataset_paths: list[Path],
    base_out: Path | None,
    n_limit: int | None = None,
    concurrency: int = 32,
    *,
    client: AsyncOpenAI,
):
    """Run eval pipeline. `client` (AsyncOpenAI) is required and must be injected by caller."""

    # ---- Helpers for Responses-native inputs ----
    def _responses_join_text(parts: Any) -> str:
        if isinstance(parts, str):
            return parts
        if parts is None:
            return ""
        try:
            parsed_parts = TypeAdapter(list[ResponseContentPart]).validate_python(parts)
            return "\n".join(iter_resolved_text(parsed_parts))
        except Exception:
            return ""

    def responses_prev_assistant_index(inp: Any) -> int | None:
        parsed = parse_response_messages(inp)
        if parsed is None:
            return None
        for i in range(len(parsed) - 2, -1, -1):
            if response_message_role(parsed[i]) == MessageRole.ASSISTANT:
                return i
        return None

    def responses_extract_system_text(inp: Any) -> str:
        parsed = parse_response_messages(inp)
        if parsed is None:
            return ""
        buf: list[str] = []
        for it in parsed:
            if response_message_role(it) != MessageRole.SYSTEM:
                continue
            buf.append(response_message_content_as_text(it))
        return "\n\n".join([t for t in buf if t])

    def responses_slice_prefix(inp: Any, end_idx: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        parsed = parse_response_messages(inp)
        if parsed is None:
            return out
        for it in parsed[:end_idx]:
            role = response_message_role(it)
            if role not in (MessageRole.USER, MessageRole.ASSISTANT):
                continue
            content = it.content
            if isinstance(content, list):
                try:
                    parts = TypeAdapter(list[ResponseContentPart]).validate_python(content)
                    content = [p.model_dump(mode="json", exclude_none=True) for p in parts]
                except Exception:
                    pass
            out.append({"role": role, "content": content})
        return out

    def responses_to_ccr_messages(inp: list[ResponseOutputMessage]) -> list[ChatCompletionMessageParam]:
        msgs: list[ChatCompletionMessageParam] = []
        for it in inp:
            role = response_message_role(it)
            if role in (MessageRole.USER, MessageRole.ASSISTANT) and (
                txt := response_message_content_as_text(it).strip()
            ):
                if role == MessageRole.USER:
                    msgs.append(ChatCompletionUserMessageParam(role="user", content=txt))
                else:  # MessageRole.ASSISTANT
                    msgs.append(ChatCompletionAssistantMessageParam(role="assistant", content=txt))
        return msgs

    validate_template_file(template_path)
    # Determine output directory
    if base_out is not None:
        # Caller provided a final directory — use it directly (no nesting)
        out_dir = base_out
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = DEFAULT_BASE
        # Default layout: runs/<ts> for variants; runs/baseline-<ts> for baseline
        out_dir = base / f"baseline-{ts}" if template_path.name == "current_effective_template.txt" else base / f"{ts}"
    samples_out = out_dir / "samples.jsonl"
    grades_out = out_dir / "grades.jsonl"
    summary_out = out_dir / "summary.json"
    out_dir.mkdir(parents=True, exist_ok=True)
    # copy template in
    with suppress(Exception):
        shutil.copyfile(template_path, out_dir / "template.txt")
    # Load dataset(s)
    # Load dataset(s) and concatenate
    dataset: list[Sample] = []
    for p in dataset_paths:
        dataset.extend(await read_dataset(p))
    total = len(dataset)
    if n_limit is not None:
        dataset = dataset[: max(0, int(n_limit))]
    selected = len(dataset)
    print(
        json.dumps(
            {
                "event": "startup",
                "dataset_paths": [str(p) for p in dataset_paths],
                "total": total,
                "selected": selected,
                "sampler_model": SAMPLER_MODEL,
                "grader_model": GRADER_MODEL,
            }
        )
    )

    progress_path = out_dir / "progress.jsonl"

    def log_event(event: dict[str, Any]):
        print(json.dumps(event))
        with progress_path.open("a", encoding="utf-8") as pg:
            pg.write(json.dumps(event) + "\n")

    counters = {"processed": 0, "skipped_input_tokens": 0, "sampler_errors": 0, "grader_errors": 0}

    # client is injected by caller (no implicit AsyncOpenAI() here)
    if client is None:
        raise ValueError("run_eval requires a non-None AsyncOpenAI client injected by caller")
    sem = asyncio.Semaphore(max(1, int(concurrency)))

    async def process(item: Sample) -> tuple[dict | None, dict | None]:
        async with sem:
            log_event({"event": "process_start", "cid": item.correlation_id})
            # Branch by source without coercing persisted formats
            if isinstance(item, CCRSample):  # CCR
                # 1) Rewrite system via Node apply script
                ar = item.anthropic_request
                new_sys = rewrite_system_with_template(ar.system or "", template_path)
                # 2) Find last assistant message in Anthropic messages (before final user complaint)
                prev_asst_idx = index_of_last_assistant_in_anthropic_messages(ar.messages)
                if prev_asst_idx is None:
                    log_event({"correlation_id": item.correlation_id, "status": "no_prev_assistant"})
                    return None, None
                # 3) Build OpenAI sampling request BEFORE the bad assistant turn
                context_messages = ar.messages[:prev_asst_idx]
                oai_messages = anthropic_to_chat_messages(context_messages, new_sys)
                in_tokens = tokens_for_chat_messages(oai_messages)
                log_event(
                    {
                        "event": "sampler_tokens",
                        "cid": item.correlation_id,
                        "in_tokens": in_tokens,
                        "model": SAMPLER_MODEL,
                    }
                )
                if in_tokens > MAX_INPUT_TOKENS:
                    counters["skipped_input_tokens"] += 1
                    log_event(
                        {
                            "correlation_id": item.correlation_id,
                            "status": "skipped_input_too_large",
                            "input_tokens": in_tokens,
                        }
                    )
                    return None, None
                samp_max = max(1, min(PER_OUTPUT_CAP, MAX_TOTAL_TOKENS - in_tokens - SAFETY_TOKENS))
                tools_param = ar.tools
                chat_tools = convert_responses_tools_to_chat_functions(tools_param)
                samp_req = {
                    "model": SAMPLER_MODEL,
                    "messages": dump_chat_messages(oai_messages),
                    "tools": chat_tools,
                    "tool_choice": "auto",
                    "parallel_tool_calls": True,
                    "max_completion_tokens": samp_max,
                }
                try:
                    samp = await chat_create_with_retries(
                        client, **{k: v for k, v in samp_req.items() if v is not None}
                    )
                except Exception as e:
                    counters["sampler_errors"] += 1
                    msg = {"correlation_id": item.correlation_id, "status": "sampler_error", "error": str(e)}
                    log_event(msg)
                    return None, None
                new_asst_obj = ChatAssistantMessage(message=samp.choices[0].message)
                # For grader context: convert full Anthropic message list to ChatCompletionMessageParam
                msgs_for_grader = anthropic_messages_to_standard(ar.messages)
                prev_asst_idx_for_grader: int = prev_asst_idx
            else:
                # Crush / Responses-native path
                payload = item.oai_request
                inp = payload.get("input")
                # Extract original system and rewrite via Python fallback
                orig_sys = responses_extract_system_text(inp)
                new_sys = rewrite_system_with_template(orig_sys, template_path)
                # Find boundary and build context input (drop original system items)
                prev_idx = responses_prev_assistant_index(inp)
                if prev_idx is None:
                    log_event({"correlation_id": item.correlation_id, "status": "no_prev_assistant"})
                    return None, None
                input_prefix = responses_slice_prefix(inp, prev_idx)
                # Prepend rewritten system entry
                resp_input = [{"role": "system", "content": [{"type": "input_text", "text": new_sys}]}, *input_prefix]
                base_req: dict[str, Any] = dict(payload) if isinstance(payload, dict) else {}
                base_req["input"] = resp_input
                if not base_req.get("model"):
                    base_req["model"] = SAMPLER_MODEL
                samp_req = cast(dict[str, Any], base_req)
                try:
                    samp = await responses_create_with_retries(client, **samp_req)
                except Exception as e:
                    counters["sampler_errors"] += 1
                    msg = {"correlation_id": item.correlation_id, "status": "sampler_error", "error": str(e)}
                    log_event(msg)
                    return None, None
                new_asst_obj = ResponsesAssistantMessage(responses_input=resp_input, responses_output=samp)
                # For grader context later, build ephemeral CCR-like messages
                parsed_inp = parse_response_messages(inp)
                if parsed_inp is None:
                    log_event({"correlation_id": item.correlation_id, "status": "invalid_responses_input"})
                    return None, None
                msgs_for_grader = responses_to_ccr_messages(parsed_inp)
                prev_asst_idx_for_grader = index_of_last_assistant_before_final(msgs_for_grader) or 0

            # 4) Build grading inputs
            msgs = msgs_for_grader
            base_prefix = msgs[:-2] if len(msgs) >= 2 else []
            base_prefix = [m for m in base_prefix if m.role != MessageRole.SYSTEM]
            # Compute bad branch (inclusive of complaint)
            complaint_idx = len(msgs) - 1
            bad_branch = msgs[prev_asst_idx_for_grader : complaint_idx + 1]
            # Keep first 5 and last 5; truncate middle to fit token budget
            first = base_prefix[:5]
            tail = base_prefix[-5:] if len(base_prefix) > 5 else []
            middle = base_prefix[5 : len(base_prefix) - len(tail)] if len(base_prefix) > 10 else []

            # Build a provisional grader input to compute tokens; start from minimal
            prefix_msgs = [*first]  # start with first only
            gi = build_grader_prompt(prefix_msgs + tail, bad_branch, new_asst_obj)
            tok = tokens_for_chat_messages(gi)
            # Greedily add middle messages until we hit budget
            added = 0
            for m in middle:
                trial = build_grader_prompt([*prefix_msgs, m, *tail], bad_branch, new_asst_obj)
                trial_tok = tokens_for_chat_messages(trial)
                if trial_tok <= TARGET_PREFIX_TOKENS:
                    prefix_msgs.append(m)
                    gi = trial
                    tok = trial_tok
                    added += 1
                else:
                    break
            # Attach tail (already accounted in gi)
            prefix_msgs = prefix_msgs + tail
            # Log truncation info
            log_event(
                {
                    "correlation_id": item.correlation_id,
                    "status": "grader_prefix_built",
                    "prefix_counts": {
                        "total": len(base_prefix),
                        "kept_first": len(first),
                        "kept_last": len(tail),
                        "added_middle": added,
                    },
                    "token_estimate": tok,
                }
            )
            grader_messages = build_grader_prompt(prefix_msgs, bad_branch, new_asst_obj)
            grader_input = [
                {"role": m["role"], "content": m["content"]}
                for m in [
                    {"role": "system", "content": grader_messages[0]["content"]},
                    {"role": "user", "content": grader_messages[1]["content"]},
                ]
            ]
            in_tokens_g = tokens_for_chat_messages(grader_input)
            if in_tokens_g > MAX_INPUT_TOKENS:
                counters["skipped_input_tokens"] += 1
                log_event(
                    {
                        "correlation_id": item.correlation_id,
                        "status": "grader_skipped_input_too_large",
                        "input_tokens": in_tokens_g,
                    }
                )
                return None, None
            grade_max = max(1, min(PER_OUTPUT_CAP, MAX_TOTAL_TOKENS - in_tokens_g - SAFETY_TOKENS))
            grade_req = {
                "model": GRADER_MODEL,
                "input": grader_input,
                "tools": [GRADE_TOOL],
                "tool_choice": {"type": "function", "name": "grade"},
                "parallel_tool_calls": False,
                "max_output_tokens": grade_max,
            }
            try:
                grade = await responses_create_with_retries(client, **grade_req)
            except Exception as e:
                counters["grader_errors"] += 1
                msg = {"correlation_id": item.correlation_id, "status": "grader_error", "error": str(e)}
                log_event(msg)
                return None, None
            # Validate grade parse
            try:
                _ = parse_grade_from_responses(grade)
            except Exception as e:
                counters["grader_errors"] += 1
                msg = {"correlation_id": item.correlation_id, "status": "grader_parse_error", "error": str(e)}
                log_event(msg)
                return None, None

            # Return combined records for saving
            sample_rec: dict[str, Any] = {
                "request": samp_req,
                "response": samp.model_dump(),
                "new_assistant_message": raw_new_asst_obj,
                "correlation_id": item.correlation_id,
                "timestamp": item.timestamp,
            }
            if isinstance(item, CCRSample):
                sample_rec["anthropic_request"] = item.anthropic_request
            return (
                sample_rec,
                {
                    "request": grade_req,
                    "response": grade.model_dump(),
                    "correlation_id": item.correlation_id,
                    "timestamp": item.timestamp,
                },
            )

    # Build tasks and run aggregator loop (dedented from process)
    tasks = [process(item) for item in dataset]
    log_event({"event": "tasks_built", "count": len(tasks)})

    scores: list[float] = []
    # Secondary metrics: tooling usage
    tool_stats = {
        "total_samples": 0,
        "text_only": 0,
        "with_tools": 0,
        "function_counts": {},  # name -> count of tool calls
    }
    # Per-source accumulators
    scores_by_source: dict[str, list[float]] = {"ccr": [], "crush": []}
    tool_stats_by_source: dict[str, dict[str, Any]] = {
        "ccr": {"total_samples": 0, "text_only": 0, "with_tools": 0, "function_counts": {}},
        "crush": {"total_samples": 0, "text_only": 0, "with_tools": 0, "function_counts": {}},
    }

    def compute_and_write_summary(_final: bool = False) -> dict[str, Any]:
        # Secondary metrics helpers
        total_samples = tool_stats.get("total_samples", 0)
        text_only = tool_stats.get("text_only", 0)
        with_tools = tool_stats.get("with_tools", 0)
        fc = cast(dict[str, int], tool_stats.get("function_counts", {}))
        total_tool_calls = sum(fc.values()) if fc else 0
        function_pct = {k: (v / total_tool_calls) if total_tool_calls > 0 else 0.0 for k, v in fc.items()}

        # CI helpers (normal approx, 95%)
        def _mk_basic(scores_list: list[float]) -> tuple[float, float, float, float]:
            if not scores_list:
                return 0.0, 0.0, 0.0, 0.0
            m = sum(scores_list) / len(scores_list)
            v = (sum((x - m) ** 2 for x in scores_list) / (len(scores_list) - 1)) if len(scores_list) > 1 else 0.0
            se_ = math.sqrt(v / len(scores_list)) if len(scores_list) > 0 else 0.0
            ci_ = 1.96 * se_
            return m, ci_, m - ci_, m + ci_

        # Compute mean and CI for overall scores
        mean, ci95, lcb, ucb = _mk_basic(scores)

        by_source: dict[str, Any] = {}
        for sname in ("ccr", "crush"):
            m_s, _ci_s, l_s, u_s = _mk_basic(scores_by_source[sname])
            ts_s = tool_stats_by_source[sname]
            total_s = ts_s["total_samples"] or 0
            fc_s = cast(dict[str, int], ts_s.get("function_counts", {}))
            total_tool_calls_s = sum(fc_s.values()) if fc_s else 0
            func_pct_s = {k: (v / total_tool_calls_s) if total_tool_calls_s > 0 else 0.0 for k, v in fc_s.items()}
            by_source[sname] = {
                "n": len(scores_by_source[sname]),
                "mean": m_s,
                "ci95": {"lcb": l_s, "ucb": u_s},
                "tooling": {
                    "total_samples": total_s,
                    "text_only_pct": ((ts_s["text_only"] / total_s) if total_s else 0.0),
                    "with_tools_pct": ((ts_s["with_tools"] / total_s) if total_s else 0.0),
                    "function_counts": ts_s["function_counts"],
                    "function_pct": func_pct_s,
                },
            }
        summary = {
            "n": len(scores),
            "mean": mean,
            "ci95": {"lcb": lcb, "ucb": ucb},
            "counters": counters,
            "models": {"sampler": SAMPLER_MODEL, "evaluator": GRADER_MODEL},
            "tooling": {
                "total_samples": total_samples,
                "text_only_pct": ((text_only / total_samples) if total_samples > 0 else 0.0),
                "with_tools_pct": ((with_tools / total_samples) if total_samples > 0 else 0.0),
                "function_counts": fc,
                "function_pct": function_pct,
            },
            "by_source": by_source,
        }
        with summary_out.open("w", encoding="utf-8") as f:
            json.dump(summary, f, sort_keys=True)
        return summary

    with samples_out.open("w", encoding="utf-8") as s_out, grades_out.open("w", encoding="utf-8") as g_out:
        log_event({"event": "as_completed_start", "count": len(tasks)})
        for fut in asyncio.as_completed(tasks):
            samp_rec, grade_rec = await fut
            # Determine source from sampling record shape
            src = None
            if samp_rec:
                rec_obj = EvalSampleRecord.model_validate(samp_rec)
                s_out.write(json.dumps(rec_obj.model_dump(), sort_keys=True) + "\n")
                # Determine source from message type
                src = "crush" if isinstance(rec_obj.new_assistant_message, ResponsesAssistantMessage) else "ccr"
                # Update tool usage stats
                tool_stats["total_samples"] = tool_stats.get("total_samples", 0) + 1
                # Extract tool calls from ChatAssistantMessage
                tcs = []
                if isinstance(rec_obj.new_assistant_message, ChatAssistantMessage):
                    _tcs = rec_obj.new_assistant_message.message.tool_calls
                    tcs = list(_tcs) if _tcs is not None else []
                if not tcs:
                    tool_stats["text_only"] = tool_stats.get("text_only", 0) + 1
                else:
                    tool_stats["with_tools"] = tool_stats.get("with_tools", 0) + 1
                    fc_top = cast(dict[str, int], tool_stats["function_counts"])  # type: ignore[index]
                    for tc in tcs:
                        fn = tc.function.name if tc.function else "UNKNOWN"
                        fc_top[fn] = fc_top.get(fn, 0) + 1
                # Per-source tool stats
                if src in tool_stats_by_source:
                    src_stats = tool_stats_by_source[src]
                    src_stats["total_samples"] = src_stats.get("total_samples", 0) + 1
                    if not tcs:
                        src_stats["text_only"] = src_stats.get("text_only", 0) + 1
                    else:
                        src_stats["with_tools"] = src_stats.get("with_tools", 0) + 1
                        ts_fc = cast(dict[str, int], src_stats["function_counts"])  # type: ignore[index]
                        for tc in tcs:
                            fn = tc.function.name if tc.function else "UNKNOWN"
                            ts_fc[fn] = ts_fc.get(fn, 0) + 1
            if grade_rec:
                g_obj = EvalGradeRecord.model_validate(grade_rec)
                g_out.write(json.dumps(g_obj.model_dump(), sort_keys=True) + "\n")
                try:
                    response_obj = parse_response(g_obj.response)
                    grade = parse_grade_from_responses(response_obj)
                    score = float(grade.score)
                    scores.append(score)
                    if src in scores_by_source:
                        scores_by_source[src].append(score)  # type: ignore[index]
                    counters["processed"] += 1
                    summary_data = compute_and_write_summary(False)
                    print(
                        json.dumps(
                            {
                                "event": "grade_parsed",
                                "cid": g_obj.correlation_id,
                                "score": score,
                                "source": src,
                                "n": summary_data["n"],
                                "mean": summary_data["mean"],
                                "ci95": summary_data["ci95"],
                                "models": summary_data["models"],
                            }
                        )
                    )
                except Exception as e:
                    counters["grader_errors"] += 1
                    log_event({"status": "aggregate_parse_error", "error": str(e)})

    # Final summary after all grades
    s_final = compute_and_write_summary(True)
    log_event(
        {
            "event": "summary_final",
            "n": s_final["n"],
            "mean": s_final["mean"],
            "ci95": s_final["ci95"],
            "models": s_final["models"],
        }
    )

    # Generate HTML report summarizing sequences per sample
    def _generate_html_report(report_base: Path):
        samples_path = report_base / "samples.jsonl"
        grades_path = report_base / "grades.jsonl"
        report_path = report_base / "report.html"
        # Build grades map
        grades_map: dict[str, Grade] = {}
        with grades_path.open("r", encoding="utf-8") as gf:
            for line in gf:
                grec = EvalGradeRecord.model_validate_json(line)
                cid = grec.correlation_id
                if not cid:
                    continue
                response_obj = parse_response(grec.response)
                grade = parse_grade_from_responses(response_obj)
                grades_map[cid] = grade

        # Collect rows
        rows: list[dict[str, Any]] = []

        summary: dict[str, Any] = {}
        with (report_base / "summary.json").open("r", encoding="utf-8") as sf:
            summary = json.load(sf)

        template_file = report_base / "template.txt"

        with samples_path.open("r", encoding="utf-8") as sf:
            for line in sf:
                srec = json.loads(line)
                sample_record = EvalSampleRecord.model_validate(srec)
                cid = sample_record.correlation_id or ""

                # Two display paths depending on source
                if isinstance(sample_record.new_assistant_message, ResponsesAssistantMessage):
                    # Crush item: reconstruct minimal views from responses_input
                    rin = sample_record.new_assistant_message.responses_input
                    orig_sys = responses_extract_system_text(rin)
                    rewritten_sys = rewrite_system_with_template(orig_sys or "", template_file)
                    parsed_rin = parse_response_messages(rin)
                    msgs_disp = responses_to_ccr_messages(parsed_rin) if parsed_rin else []
                    idx = index_of_last_assistant_before_final(msgs_disp)
                    if idx is None:
                        shared_prefix = msgs_disp
                        bad_branch = []
                    else:
                        shared_prefix = [m for m in (msgs_disp[:idx]) if m.role != MessageRole.SYSTEM]
                        bad_branch = msgs_disp[idx:]
                else:
                    # CCR item - validate and use typed Anthropic structures
                    if sample_record.anthropic_request is None:
                        continue
                    orig_sys = sample_record.anthropic_request.system or ""
                    rewritten_sys = rewrite_system_with_template(orig_sys, template_file)
                    msgs = anthropic_messages_to_standard(sample_record.anthropic_request.messages)
                    idx = index_of_last_assistant_before_final(msgs)
                    if idx is None:
                        shared_prefix = msgs
                        bad_branch = []
                    else:
                        shared_prefix = [m for m in (msgs[:idx]) if m.role != MessageRole.SYSTEM]
                        bad_branch = msgs[idx:]
                grade = grades_map.get(cid)
                rows.append(
                    {
                        "correlation_id": cid,
                        "timestamp": sample_record.timestamp,
                        "orig_system": orig_sys,
                        "rewritten_system": rewritten_sys,
                        "shared_prefix": shared_prefix,
                        "bad_branch": bad_branch,
                        "alternative": sample_record.new_assistant_message.model_dump(),
                        "grade": grade,
                    }
                )

        # Jinja2 template
        env = Environment(
            loader=FileSystemLoader(str(Path(__file__).parent / "templates")),
            autoescape=select_autoescape(["html", "xml"]),
        )
        template = env.get_template("report.html.j2")
        html_text = template.render(rows=rows, summary=summary)
        report_path.write_text(html_text, encoding="utf-8")

    _generate_html_report(out_dir)
    # Emit report path for convenience
    report_path = out_dir / "report.html"
    print(json.dumps({"event": "report_written", "path": str(report_path)}))
    print(str(report_path))


def main():
    args = parse_args()
    # Allow mixing multiple datasets in one run via repeated --dataset
    dataset_paths: list[Path] = [Path(p) for p in (args.dataset if args.dataset is not None else [])]
    if not dataset_paths:
        dataset_paths = [DEFAULT_DATASET_PATH]
    base_out = Path(args.out_dir) if args.out_dir else None
    asyncio.run(
        run_eval(Path(args.template), dataset_paths, base_out, args.n, args.concurrency, client=get_async_openai())
    )
