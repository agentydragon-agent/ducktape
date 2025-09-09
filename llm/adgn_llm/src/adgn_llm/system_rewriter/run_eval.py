import argparse
import asyncio
import copy
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from importlib import resources
from contextlib import suppress
import tiktoken
from .constants import TOOLS_HEADER
from jinja2 import Environment, FileSystemLoader, select_autoescape
from openai import AsyncOpenAI
from adgn_llm.openai_retry import responses_create_with_retries, chat_create_with_retries
from .schemas import (
    CCRRequest,
    CCRSample,
    CrushSample,
    EvalGradeRecord,
    EvalSampleRecord,
    Sample,
)

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
REWRITE_APPLY = resources.files("adgn_llm.system_rewriter").joinpath("js/system_rewrite_apply.js")

from .templates import validate_template_file


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
    ap.add_argument(
        "--n",
        type=int,
        default=None,
        help="Limit number of samples to process",
    )
    ap.add_argument(
        "--concurrency",
        type=int,
        default=32,
        help="Number of samples to run in parallel",
    )
    return ap.parse_args()


async def read_dataset(dataset_path: Path) -> list[Sample]:
    items: list[Sample] = []
    with dataset_path.open("r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            # Support both CCR (anthropic_request) and Crush (oai_request) entries
            if "anthropic_request" in rec:
                # Validate CCR sample via Pydantic model
                ccr = CCRSample(
                    correlation_id=rec.get("correlation_id"),
                    timestamp=rec.get("timestamp"),
                    anthropic_request=CCRRequest.model_validate(rec["anthropic_request"]),  # type: ignore[arg-type]
                )
                items.append(ccr)
                continue
            if "oai_request" in rec:
                # For ingest, keep unvalidated payload; some test fixtures include relaxed shapes
                payload = rec["oai_request"]
                crush = CrushSample(
                    correlation_id=rec.get("correlation_id"),
                    timestamp=rec.get("timestamp"),
                    oai_request=payload,  # type: ignore[arg-type]
                    wirelog=rec.get("wirelog"),
                )
                items.append(crush)
                continue
    return items


# --- OpenAI client ---


def estimate_tokens(text: str) -> int:
    enc = tiktoken.get_encoding("cl100k_base")
    # Encode special-token-looking sequences as plain text (no ValueError)
    return len(enc.encode(text, disallowed_special=()))


def tokens_for_chat_messages(msgs: list[dict[str, Any]]) -> int:
    parts: list[str] = []
    for m in msgs:
        parts.append(str(m.get("role", "")))
        c = m.get("content")
        if isinstance(c, str):
            parts.append(c)
        elif isinstance(c, list):
            for p in c:
                if isinstance(p, dict) and isinstance(p.get("text"), str):
                    parts.append(p["text"])
    return estimate_tokens("\n".join(parts))


def flatten_system_string(sys: Any) -> str:
    if isinstance(sys, str):
        return sys
    if isinstance(sys, list):
        parts: list[str] = []
        for it in sys:
            if isinstance(it, dict) and it.get("type") == "text" and isinstance(it.get("text"), str):
                parts.append(it["text"])
        return "\n\n".join(parts)
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
            "Node.js ('node') not found in PATH; install Node or adjust PATH to use system rewrite",
        ) from e
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr.decode("utf-8", errors="ignore"))
        raise RuntimeError(f"system rewrite failed with code {proc.returncode}")
    return proc.stdout.decode("utf-8")


ENV_INTRO = "Here is useful information about the environment you are running in:"
MODEL_PREFIX = "You are powered by the model"
MCP_HEADER = "# MCP Server Instructions"


def prev_assistant_index(msgs: list[dict[str, Any]]) -> int | None:
    """Return the index of the last assistant message before the final item, or None."""
    if not isinstance(msgs, list):
        return None
    for i in range(len(msgs) - 2, -1, -1):
        if isinstance(msgs[i], dict) and msgs[i].get("role") == "assistant":
            return i
    return None


def map_tools_for_chat(tools_val):
    """Map Responses-style tools to Chat Completions function tool schema."""

    def _to_chat_tool(t: Any):
        if not isinstance(t, dict):
            return None
        # Normalize to a bare function dict first
        if t.get("type") == "function" and isinstance(t.get("function"), dict):
            fn = dict(t["function"])  # shallow copy
        else:
            fn = dict(t)
        # Convert Responses API shape -> Chat Completions shape
        if "input_schema" in fn and "parameters" not in fn:
            fn["parameters"] = fn.pop("input_schema")
        # Remove unsupported keys
        fn.pop("strict", None)
        # Keep only standard Chat function keys
        out_fn = {k: v for k, v in fn.items() if k in ("name", "description", "parameters")}
        if not isinstance(out_fn.get("name"), str):
            return None
        if "parameters" not in out_fn:
            return None
        return {"type": "function", "function": out_fn}

    out = []
    if isinstance(tools_val, list):
        for t in tools_val:
            if ct := _to_chat_tool(t):
                out.append(ct)
    return out or None


def anthro_to_openai_messages(
    body: dict[str, Any],
    new_system_text: str | None,
) -> list[dict[str, Any]]:
    """Translate Anthropic messages into OpenAI Chat format, preserving:
    - assistant tool_calls (from Anthropic tool_use parts)
    - tool results as role="tool" messages (from Anthropic tool_result parts)
    - user/assistant plain text
    Avoid emitting empty messages.
    """

    def _join_text_parts(parts: list[dict[str, Any]]) -> str:
        texts: list[str] = []
        for p in parts:
            if isinstance(p, dict) and p.get("type") == "text" and isinstance(p.get("text"), str):
                texts.append(p["text"])
        return "\n".join(texts)

    out: list[dict[str, Any]] = []
    if new_system_text:
        out.append({"role": "system", "content": new_system_text})

    for m in body.get("messages", []):
        role = m.get("role")
        content = m.get("content")

        # Simple string content
        if isinstance(content, str):
            if role in ("user", "assistant") and content.strip():
                out.append({"role": role, "content": content})
            # ignore system here (we already injected rewritten system)
            continue

        # Structured content list
        if isinstance(content, list):
            if role == "assistant":
                text_buf: list[str] = []
                tool_calls: list[dict[str, Any]] = []
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    ptype = part.get("type")
                    if ptype == "text" and isinstance(part.get("text"), str):
                        text_buf.append(part["text"])
                    elif ptype == "tool_use":
                        # Map to OpenAI function call with required id
                        name = part.get("name")
                        args = part.get("input")
                        tcid = part.get("id") or part.get("tool_use_id")
                        # Remove extra nesting if input is a singleton list: [ {...} ] -> {...}
                        if isinstance(args, list) and len(args) == 1:
                            args = args[0]
                        # Preserve original JSON argument string if already a string; else serialize deterministically
                        if isinstance(args, str):
                            args_str = args  # preserve exactly
                        else:
                            try:
                                # Minified JSON, preserve key order (no sort_keys), no spaces
                                args_str = json.dumps(
                                    args if args is not None else {},
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                )
                            except Exception as e:
                                raise RuntimeError(
                                    f"FATAL: Unserializable tool_use.input for function '{name}': {e}",
                                )
                        tool_call: dict[str, Any] = {
                            "type": "function",
                            "function": {
                                "name": name or "unknown",
                                "arguments": args_str,
                            },
                        }
                        if tcid:
                            tool_call["id"] = str(tcid)
                        tool_calls.append(tool_call)
                if text_buf or tool_calls:
                    msg: dict[str, Any] = {"role": "assistant"}
                    if text_buf:
                        msg["content"] = "\n".join(text_buf)
                    else:
                        msg["content"] = None  # no empty-string content when only tool_calls
                    if tool_calls:
                        msg["tool_calls"] = tool_calls
                    out.append(msg)
                continue

            if role == "user":
                text_parts: list[dict[str, Any]] = []
                tool_msgs: list[dict[str, Any]] = []
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    ptype = part.get("type")
                    if ptype == "text":
                        text_parts.append(part)
                    elif ptype == "tool_result":
                        # Emit as a tool role message
                        tcid = part.get("tool_use_id") or part.get("id")
                        # tool_result content may itself be list-of-text or string
                        tcontent = part.get("content")
                        if isinstance(tcontent, str):
                            tool_text = tcontent
                        elif isinstance(tcontent, list):
                            tool_text = _join_text_parts(tcontent)
                        else:
                            try:
                                tool_text = json.dumps(
                                    tcontent,
                                    ensure_ascii=False,
                                    sort_keys=True,
                                )
                            except Exception as e:
                                raise RuntimeError(
                                    f"FATAL: Unserializable tool_result.content: {e}",
                                )
                        # Emit tool result; if missing id, keep but mark unknown to avoid silent drop
                        if tcid:
                            tool_msgs.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": str(tcid),
                                    "content": tool_text or "",
                                },
                            )
                        # If tcid missing, drop the tool message to avoid invalid Chat linkage
                # Order: tool messages first (to mirror CCR), then user text (if any)
                out.extend(
                    [tm for tm in tool_msgs if (tm.get("content") or tm.get("tool_call_id"))],
                )
                txt = _join_text_parts(text_parts)
                if txt.strip():
                    out.append({"role": "user", "content": txt})
                continue

            if role == "tool":
                # Allow direct tool messages in source (e.g., when normalizing from other formats)
                content_val = None
                if isinstance(content, str):
                    content_val = content
                elif isinstance(content, list):
                    content_val = _join_text_parts(content)
                # Preserve explicit tool_call_id if present on the message
                tcid = m.get("tool_call_id") or m.get("tool_use_id") or m.get("id")
                if tcid:
                    out.append(
                        {
                            "role": "tool",
                            "tool_call_id": str(tcid),
                            "content": content_val or "",
                        },
                    )
                # If tcid missing, drop this tool message
                continue

            # Ignore any other roles or system lists here
            continue

    return out


def anthro_to_responses_input(
    body: dict[str, Any],
    new_system_text: str | None,
) -> list[dict[str, Any]]:
    """Translate Anthropic-style messages into OpenAI Responses API input array."""

    def _join_text_parts(parts: list[dict[str, Any]]) -> str:
        texts: list[str] = []
        for p in parts:
            if isinstance(p, dict) and p.get("type") == "text" and isinstance(p.get("text"), str):
                texts.append(p["text"])
        return "\n".join(texts)

    out: list[dict[str, Any]] = []
    if new_system_text:
        out.append(
            {
                "role": "system",
                "content": [{"type": "input_text", "text": new_system_text}],
            }
        )
    for m in body.get("messages", []):
        role = m.get("role")
        content = m.get("content")
        if role not in ("user", "assistant"):
            continue
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = _join_text_parts(content)
        else:
            text = ""
        if text.strip():
            out.append(
                {
                    "role": role,
                    "content": [{"type": "input_text", "text": text}],
                }
            )
    return out


def build_grader_prompt(
    prefix_messages: list[dict[str, Any]],
    raw_bad_branch: list[dict[str, Any]],
    raw_new_asst_obj: dict[str, Any],
) -> list[dict[str, Any]]:
    sys = {
        "role": "system",
        "content": (
            "You are an evaluator of AI coding assistants.\n\n"
            "You will be given a past conversation between user and an AI coding assistant."
            " The conversation ends with a turn where assistant's next action or response was bad quality, and user"
            " marked that by the marker token '<bad>' in their subsequent message along with some explanation of"
            " what assistant did wrong. You will be given a counterfactual NEW alternative response that assistant"
            " could have sent or immediate next action assistant could have taken instead of the bad actions."
            " Your task is to evaluate whether the alternative action/response would be better to take as an immediate action"
            " than the action the user complained about.\n\n"
            " Note that in the alternative action branch, you only see 1 next action - if it contains a tool use,"
            " assistant would have been able to potentially follow it up with further actions.\n\n"
            'A "tool_calls" key in the alternative action JSON indicates that assistant would have used a tool.'
            " After that tool use, it would then have opportunity to potentially continue with further actions."
            ' If the alternative action does not have any "tool_calls", then assistant would have stopped after this action/message.'
            "\n\n"
            " Use the rubric: 1=worse/still bad; 2=minor/no improvement; 3=partially improved;"
            " 4=mostly fixed; 5=completely fixed.\n\n"
            "Read the conversation for context, read the original bad branch and the new assistant action/response,"
            " and use the 'grade' tool to return a 1-5 score of the new response and a rationale."
        ),
    }
    user = {
        "role": "user",
        "content": (
            "The following is a past conversation between user and an AI coding assistant:\n"
            + json.dumps(prefix_messages, ensure_ascii=False)
            + "\n\n"
            + "BAD_BRANCH_JSON (from bad assistant turn through the user's complaint, inclusive):\n"
            + json.dumps(raw_bad_branch or [], ensure_ascii=False)
            + "\n\n"
            + "NEW_ASSISTANT_REPLY_JSON:\n"
            + json.dumps(raw_new_asst_obj or {}, ensure_ascii=False)
        ),
    }
    return [sys, user]


GRADE_TOOL = {
    "type": "function",
    "name": "grade",
    "description": "Return a 1-5 score and a short rationale.",
    "parameters": {
        "type": "object",
        "properties": {
            "score": {"type": "integer", "minimum": 1, "maximum": 5},
            "rationale": {"type": "string"},
        },
        "required": ["score", "rationale"],
        "additionalProperties": False,
    },
    "strict": True,
}


def parse_grade_from_responses(resp_obj) -> dict[str, Any]:
    data = resp_obj if isinstance(resp_obj, dict) else resp_obj.model_dump()
    out = data.get("output", []) or []
    for item in out:
        if item.get("type") == "function_call" and item.get("name") == "grade":
            return json.loads(item.get("arguments", "{}"))
    raise RuntimeError("No grade tool call in responses output")


async def run_eval(
    template_path: Path,
    dataset_paths: list[Path],
    base_out: Path | None,
    n_limit: int | None = None,
    concurrency: int = 32,
):
    # ---- Helpers for Responses-native inputs ----
    def _responses_join_text(parts: Any) -> str:
        if isinstance(parts, str):
            return parts
        if isinstance(parts, list):
            texts: list[str] = []
            for c in parts:
                if isinstance(c, dict):
                    t = c.get("text") or c.get("input_text") or c.get("content")
                    if isinstance(t, str):
                        texts.append(t)
            return "\n".join(texts)
        return ""

    def responses_prev_assistant_index(inp: Any) -> int | None:
        if not isinstance(inp, list):
            return None
        for i in range(len(inp) - 2, -1, -1):
            it = inp[i]
            if isinstance(it, dict) and (it.get("role") or "").lower() == "assistant":
                return i
        return None

    def responses_extract_system_text(inp: Any) -> str:
        if not isinstance(inp, list):
            return ""
        buf: list[str] = []
        for it in inp:
            if not isinstance(it, dict):
                continue
            if (it.get("role") or "").lower() != "system":
                continue
            buf.append(_responses_join_text(it.get("content")))
        return "\n\n".join([t for t in buf if t])

    def responses_slice_prefix(inp: Any, end_idx: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if not isinstance(inp, list):
            return out
        for it in inp[:end_idx]:
            if not isinstance(it, dict):
                continue
            role = (it.get("role") or "").lower()
            if role not in ("user", "assistant"):
                continue
            # Keep content shape as-is (Responses input parts)
            out.append({"role": role, "content": it.get("content")})
        return out

    def responses_to_ccr_messages(inp: Any) -> list[dict[str, Any]]:
        msgs: list[dict[str, Any]] = []
        if not isinstance(inp, list):
            return msgs
        for it in inp:
            if not isinstance(it, dict):
                continue
            role = (it.get("role") or "").lower()
            if role in ("user", "assistant"):
                txt = _responses_join_text(it.get("content"))
                if txt.strip():
                    msgs.append({"role": role, "content": txt})
        return msgs

    validate_template_file(template_path)
    # Determine output directory
    if base_out is not None:
        # Caller provided a final directory — use it directly (no nesting)
        out_dir = base_out
    else:
        ts = int(time.time())
        base = DEFAULT_BASE
        # Default layout: runs/<ts> for variants; runs/baseline-<ts> for baseline
        if template_path.name == "current_effective_template.txt":
            out_dir = base / f"baseline-{ts}"
        else:
            out_dir = base / f"{ts}"
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
            },
        ),
    )

    progress_path = out_dir / "progress.jsonl"

    def log_event(event: dict[str, Any]):
        print(json.dumps(event))
        with progress_path.open("a", encoding="utf-8") as pg:
            pg.write(json.dumps(event) + "\n")

    counters = {
        "processed": 0,
        "skipped_input_tokens": 0,
        "sampler_errors": 0,
        "grader_errors": 0,
    }

    client = AsyncOpenAI()
    sem = asyncio.Semaphore(max(1, int(concurrency)))

    async def process(item: Sample) -> tuple[dict | None, dict | None]:
        async with sem:
            log_event({"event": "process_start", "cid": item.correlation_id})
            # Branch by source without coercing persisted formats
            if isinstance(item, CCRSample):  # CCR
                # 1) Rewrite system via Node apply script
                ar = item.anthropic_request  # type: ignore[assignment]
                sys_val = (
                    ar.system
                    if isinstance(ar.system, str)
                    else "\n\n".join([p.get("text", "") for p in (ar.system or []) if isinstance(p, dict)])
                )
                new_sys = rewrite_system_with_template(sys_val, template_path)
                # 2) Build OpenAI sampling request BEFORE the bad assistant turn
                msgs = ar.messages
                prev_asst_idx = prev_assistant_index(msgs)
                if prev_asst_idx is None:
                    log_event(
                        {
                            "correlation_id": item.correlation_id,
                            "status": "no_prev_assistant",
                        }
                    )
                    return None, None
                context_body = {"messages": msgs[:prev_asst_idx]}
                oai_messages = anthro_to_openai_messages(context_body, new_sys)
                in_tokens = tokens_for_chat_messages(oai_messages)
                log_event(
                    {
                        "event": "sampler_tokens",
                        "cid": item.correlation_id,
                        "in_tokens": in_tokens,
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
                chat_tools = map_tools_for_chat(tools_param)
                samp_req = {
                    "model": SAMPLER_MODEL,
                    "messages": oai_messages,
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
                    msg = {
                        "correlation_id": item.correlation_id,
                        "status": "sampler_error",
                        "error": str(e),
                    }
                    log_event(msg)
                    return None, None
                new_asst_obj = samp.choices[0].message.model_dump()
                # For grader context construction later
                msgs_for_grader = msgs
                prev_asst_idx_for_grader = prev_asst_idx
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
                    log_event(
                        {
                            "correlation_id": item.correlation_id,
                            "status": "no_prev_assistant",
                        }
                    )
                    return None, None
                input_prefix = responses_slice_prefix(inp, prev_idx)
                # Prepend rewritten system entry
                resp_input = [
                    {
                        "role": "system",
                        "content": [{"type": "input_text", "text": new_sys}],
                    }
                ] + input_prefix
                base_req = copy.deepcopy(payload) if isinstance(payload, dict) else {}
                base_req["input"] = resp_input
                if not base_req.get("model"):
                    base_req["model"] = SAMPLER_MODEL
                samp_req = base_req
                try:
                    samp = await responses_create_with_retries(client, **samp_req)
                except Exception as e:
                    counters["sampler_errors"] += 1
                    msg = json.dumps(
                        {
                            "correlation_id": item.correlation_id,
                            "status": "sampler_error",
                            "error": str(e),
                        }
                    )
                    log_event(msg)
                    return None, None
                new_asst_obj = {
                    "responses_input": resp_input,
                    "responses_output": samp.model_dump(),
                }
                # For grader context later, build ephemeral CCR-like messages
                msgs_for_grader = responses_to_ccr_messages(inp)
                prev_asst_idx_for_grader = prev_assistant_index(msgs_for_grader)
                if prev_asst_idx_for_grader is None:
                    prev_asst_idx_for_grader = 0

            # 4) Build grading inputs
            msgs = msgs_for_grader
            raw_new_asst_obj = new_asst_obj if isinstance(new_asst_obj, dict) else new_asst_obj.model_dump()
            base_prefix = msgs[:-2] if len(msgs) >= 2 else []
            base_prefix = [m for m in base_prefix if m.get("role") != "system"]
            # Compute bad branch (inclusive of complaint)
            complaint_idx = len(msgs) - 1
            raw_bad_branch = msgs[prev_asst_idx_for_grader : complaint_idx + 1]
            # Keep first 5 and last 5; truncate middle to fit token budget
            first = base_prefix[:5]
            tail = base_prefix[-5:] if len(base_prefix) > 5 else []
            middle = base_prefix[5 : len(base_prefix) - len(tail)] if len(base_prefix) > 10 else []

            # Build a provisional grader input to compute tokens; start from minimal
            def mk_grader_input(
                prefix_subset: list[dict[str, Any]],
            ) -> list[dict[str, Any]]:
                gm = build_grader_prompt(
                    prefix_subset,
                    raw_bad_branch,
                    raw_new_asst_obj,
                )
                return [
                    {"role": "system", "content": gm[0]["content"]},
                    {"role": "user", "content": gm[1]["content"]},
                ]

            prefix_msgs = [*first]  # start with first only
            gi = mk_grader_input(prefix_msgs + tail)
            tok = tokens_for_chat_messages(gi)
            # Greedily add middle messages until we hit budget
            added = 0
            for m in middle:
                trial = mk_grader_input([*prefix_msgs, m, *tail])
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
            grader_messages = build_grader_prompt(
                prefix_msgs,
                raw_bad_branch,
                raw_new_asst_obj,
            )
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
                    },
                )
                return None, None
            grade_max = max(
                1,
                min(PER_OUTPUT_CAP, MAX_TOTAL_TOKENS - in_tokens_g - SAFETY_TOKENS),
            )
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
                msg = {
                    "correlation_id": item.correlation_id,
                    "status": "grader_error",
                    "error": str(e),
                }
                log_event(msg)
                return None, None
            # Validate grade parse
            try:
                _ = parse_grade_from_responses(grade)
            except Exception as e:
                counters["grader_errors"] += 1
                msg = {
                    "correlation_id": item.correlation_id,
                    "status": "grader_parse_error",
                    "error": str(e),
                }
                log_event(msg)
                return None, None

            # Return combined records for saving
            return (
                {
                    "request": samp_req,
                    "response": samp.model_dump(),
                    "new_assistant_message": raw_new_asst_obj,
                    "correlation_id": item.correlation_id,
                    "timestamp": item.timestamp,
                    "anthropic_request": item.anthropic_request,
                },
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
        "ccr": {
            "total_samples": 0,
            "text_only": 0,
            "with_tools": 0,
            "function_counts": {},
        },
        "crush": {
            "total_samples": 0,
            "text_only": 0,
            "with_tools": 0,
            "function_counts": {},
        },
    }

    def compute_and_write_summary(final: bool = False) -> None:
        # Compute mean and 95% CI (normal approx)
        mean = sum(scores) / len(scores) if scores else 0.0
        var = sum((x - mean) ** 2 for x in scores) / (len(scores) - 1) if len(scores) > 1 else 0.0
        se = math.sqrt(var / len(scores)) if len(scores) > 0 else 0.0
        ci95 = 1.96 * se
        lcb = mean - ci95
        ucb = mean + ci95
        # Secondary metrics
        total_samples = tool_stats["total_samples"] or 0
        total_tool_calls = sum(tool_stats["function_counts"].values()) if tool_stats["function_counts"] else 0
        function_pct = {
            k: (v / total_tool_calls) if total_tool_calls > 0 else 0.0 for k, v in tool_stats["function_counts"].items()
        }

        # Per-source summaries
        def _mk_basic(scores_list: list[float]) -> tuple[float, float, float, float]:
            if not scores_list:
                return 0.0, 0.0, 0.0, 0.0
            m = sum(scores_list) / len(scores_list)
            v = (sum((x - m) ** 2 for x in scores_list) / (len(scores_list) - 1)) if len(scores_list) > 1 else 0.0
            se_ = math.sqrt(v / len(scores_list)) if len(scores_list) > 0 else 0.0
            ci_ = 1.96 * se_
            return m, ci_, m - ci_, m + ci_

        by_source: dict[str, Any] = {}
        for sname in ("ccr", "crush"):
            m_s, ci_s, l_s, u_s = _mk_basic(scores_by_source[sname])
            ts_s = tool_stats_by_source[sname]
            total_s = ts_s["total_samples"] or 0
            total_tool_calls_s = sum(ts_s["function_counts"].values()) if ts_s["function_counts"] else 0
            func_pct_s = {
                k: (v / total_tool_calls_s) if total_tool_calls_s > 0 else 0.0
                for k, v in ts_s["function_counts"].items()
            }
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
            "tooling": {
                "total_samples": total_samples,
                "text_only_pct": ((tool_stats["text_only"] / total_samples) if total_samples > 0 else 0.0),
                "with_tools_pct": ((tool_stats["with_tools"] / total_samples) if total_samples > 0 else 0.0),
                "function_counts": tool_stats["function_counts"],
                "function_pct": function_pct,
            },
            "by_source": by_source,
        }
        with summary_out.open("w", encoding="utf-8") as f:
            json.dump(summary, f, sort_keys=True)
        log_event(
            {
                "event": "summary_final" if final else "summary_progress",
                "n": summary["n"],
                "mean": summary["mean"],
                "ci95": summary["ci95"],
            }
        )

    with (
        samples_out.open("w", encoding="utf-8") as s_out,
        grades_out.open("w", encoding="utf-8") as g_out,
    ):
        log_event({"event": "as_completed_start", "count": len(tasks)})
        for fut in asyncio.as_completed(tasks):
            samp_rec, grade_rec = await fut
            # Determine source from sampling record shape
            src = None
            if isinstance(samp_rec, dict):
                na = samp_rec.get("new_assistant_message") or {}
                src = "crush" if isinstance(na, dict) and "responses_output" in na else "ccr"
            if samp_rec:
                rec_obj = EvalSampleRecord.model_validate(samp_rec)
                s_out.write(json.dumps(rec_obj.model_dump(), sort_keys=True) + "\n")
                # Update tool usage stats
                tool_stats["total_samples"] += 1
                nmsg = samp_rec.get("new_assistant_message") or {}
                tcs = nmsg.get("tool_calls") or []
                if not tcs:
                    tool_stats["text_only"] += 1
                else:
                    tool_stats["with_tools"] += 1
                    for tc in tcs:
                        fn = ((tc.get("function") or {}).get("name")) or "UNKNOWN"
                        tool_stats["function_counts"][fn] = tool_stats["function_counts"].get(fn, 0) + 1
                # Per-source tool stats
                if src in tool_stats_by_source:
                    ts = tool_stats_by_source[src]
                    ts["total_samples"] += 1
                    if not tcs:
                        ts["text_only"] += 1
                    else:
                        ts["with_tools"] += 1
                        for tc in tcs:
                            fn = ((tc.get("function") or {}).get("name")) or "UNKNOWN"
                            ts["function_counts"][fn] = ts["function_counts"].get(fn, 0) + 1
            if grade_rec:
                g_obj = EvalGradeRecord.model_validate(grade_rec)
                g_out.write(json.dumps(g_obj.model_dump(), sort_keys=True) + "\n")
                try:
                    parsed = parse_grade_from_responses(grade_rec["response"])  # type: ignore[index]
                    score = float(parsed.get("score", 0))
                    scores.append(score)
                    if src in scores_by_source:
                        scores_by_source[src].append(score)  # type: ignore[index]
                    counters["processed"] += 1
                    print(
                        json.dumps(
                            {
                                "event": "grade_parsed",
                                "cid": grade_rec.get("correlation_id"),
                                "score": score,
                                "source": src,
                            },
                        ),
                    )
                    compute_and_write_summary(False)
                except Exception as e:
                    counters["grader_errors"] += 1
                    log_event({"status": "aggregate_parse_error", "error": str(e)})

    # Final summary after all grades
    compute_and_write_summary(True)

    # Generate HTML report summarizing sequences per sample
    def _generate_html_report(report_base: Path):
        samples_path = report_base / "samples.jsonl"
        grades_path = report_base / "grades.jsonl"
        report_path = report_base / "report.html"
        # Build grades map
        grades_map: dict[str, dict[str, Any]] = {}
        with grades_path.open("r", encoding="utf-8") as gf:
            for line in gf:
                grec = json.loads(line)
                cid = grec.get("correlation_id")
                if not cid:
                    continue
                try:
                    parsed = parse_grade_from_responses(grec.get("response"))
                    grades_map[cid] = parsed
                except Exception:
                    grades_map[cid] = {"score": None, "rationale": None}

        # Collect rows
        rows: list[dict[str, Any]] = []

        summary: dict[str, Any] = {}
        with (report_base / "summary.json").open("r", encoding="utf-8") as sf:
            summary = json.load(sf)

        template_file = report_base / "template.txt"

        with samples_path.open("r", encoding="utf-8") as sf:
            for line in sf:
                srec = json.loads(line)
                cid = srec.get("correlation_id") or ""
                ar = srec.get("anthropic_request") or {}
                alt = srec.get("new_assistant_message") or {}
                # Two display paths depending on source
                if alt and isinstance(alt, dict) and "responses_output" in alt:
                    # Crush item: reconstruct minimal views from responses_input
                    rin = alt.get("responses_input") or []
                    orig_sys = responses_extract_system_text(rin)
                    rewritten_sys = rewrite_system_with_template(orig_sys or "", template_file)
                    msgs_disp = responses_to_ccr_messages(rin)
                    idx = prev_assistant_index(msgs_disp)
                    if idx is None:
                        shared_prefix = msgs_disp
                        bad_branch = []
                    else:
                        shared_prefix = [m for m in (msgs_disp[:idx]) if m.get("role") != "system"]
                        bad_branch = msgs_disp[idx:]
                else:
                    # CCR item
                    # Flatten original system
                    orig_sys = flatten_system_string(ar.get("system"))
                    rewritten_sys = rewrite_system_with_template(orig_sys, template_file)
                    msgs = ar.get("messages") or []
                    idx = prev_assistant_index(msgs)
                    if idx is None:
                        shared_prefix = msgs
                        bad_branch = []
                    else:
                        shared_prefix = [m for m in (msgs[:idx]) if m.get("role") != "system"]
                        bad_branch = msgs[idx:]
                grade = grades_map.get(cid) or {}
                rows.append(
                    {
                        "correlation_id": cid,
                        "timestamp": srec.get("timestamp"),
                        "orig_system": orig_sys,
                        "rewritten_system": rewritten_sys,
                        "shared_prefix": shared_prefix,
                        "bad_branch": bad_branch,
                        "alternative": alt,
                        "grade": grade,
                    },
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
    dataset_paths: list[Path] = [Path(p) for p in (args.dataset or [])]
    if not dataset_paths:
        dataset_paths = [DEFAULT_DATASET_PATH]
    base_out = Path(args.out_dir) if args.out_dir else None
    asyncio.run(run_eval(Path(args.template), dataset_paths, base_out, args.n, args.concurrency))
