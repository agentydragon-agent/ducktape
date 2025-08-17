#!/usr/bin/env python3
import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openai import AsyncOpenAI
import tiktoken  # type: ignore

# Config
DATASET_PATH = Path(__file__).parent / "data" / "dataset.jsonl"
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
REWRITE_APPLY = Path(__file__).parent / "system_rewrite_apply.js"


@dataclass
class Sample:
    correlation_id: Optional[str]
    timestamp: Optional[int]
    anthropic_request: Dict[str, Any]


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--template",
        required=True,
        help="Path to system prompt template file with ${toolsBlob}, ${envGitBlobs}, ${modelLine}, ${mcpSection}",
    )
    ap.add_argument(
        "--out-dir",
        required=False,
        help="Base output directory; a run-<ts> subfolder will be created inside it",
    )
    ap.add_argument(
        "--n", type=int, default=None, help="Limit number of samples to process"
    )
    ap.add_argument(
        "--concurrency",
        type=int,
        default=32,
        help="Number of samples to run in parallel",
    )
    return ap.parse_args()


async def read_dataset() -> List[Sample]:
    items: List[Sample] = []
    with DATASET_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            items.append(
                Sample(
                    correlation_id=rec.get("correlation_id"),
                    timestamp=rec.get("timestamp"),
                    anthropic_request=rec["anthropic_request"],
                )
            )
    return items


# --- OpenAI client ---

OPENAI_BASE = os.environ.get("OPENAI_BASE")
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")


def estimate_tokens(text: str) -> int:
    return len(tiktoken.get_encoding("cl100k_base").encode(text))


def tokens_for_chat_messages(msgs: List[Dict[str, Any]]) -> int:
    parts: List[str] = []
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
        parts: List[str] = []
        for it in sys:
            if (
                isinstance(it, dict)
                and it.get("type") == "text"
                and isinstance(it.get("text"), str)
            ):
                parts.append(it["text"])
        return "\n\n".join(parts)
    return ""


def rewrite_system_with_template(system_text: str, template_path: Path) -> str:
    # Pipe system_text into the JS apply script with the given template
    proc = subprocess.run(
        ["node", str(REWRITE_APPLY), str(template_path)],
        input=system_text.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr.decode("utf-8", errors="ignore"))
        raise RuntimeError(f"system rewrite failed with code {proc.returncode}")
    return proc.stdout.decode("utf-8")


def anthro_to_openai_messages(
    body: Dict[str, Any], new_system_text: Optional[str]
) -> List[Dict[str, Any]]:
    """Translate Anthropic messages into OpenAI Chat format, preserving:
    - assistant tool_calls (from Anthropic tool_use parts)
    - tool results as role="tool" messages (from Anthropic tool_result parts)
    - user/assistant plain text
    Avoid emitting empty messages.
    """
    def _join_text_parts(parts: List[Dict[str, Any]]) -> str:
        texts: List[str] = []
        for p in parts:
            if isinstance(p, dict) and p.get("type") == "text" and isinstance(p.get("text"), str):
                texts.append(p["text"])
        return "\n".join(texts)

    out: List[Dict[str, Any]] = []
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
                text_buf: List[str] = []
                tool_calls: List[Dict[str, Any]] = []
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
                        # Preserve original JSON argument string if already a string; else serialize deterministically
                        if isinstance(args, str):
                            args_str = args  # preserve exactly
                        else:
                            try:
                                # Minified JSON, preserve key order (no sort_keys), no spaces
                                args_str = json.dumps(args if args is not None else {}, ensure_ascii=False, separators=(",", ":"))
                            except Exception as e:
                                raise RuntimeError(f"FATAL: Unserializable tool_use.input for function '{name}': {e}")
                        tool_call: Dict[str, Any] = {
                            "type": "function",
                            "function": {"name": name or "unknown", "arguments": args_str},
                        }
                        if tcid:
                            tool_call["id"] = str(tcid)
                        tool_calls.append(tool_call)
                if text_buf or tool_calls:
                    msg: Dict[str, Any] = {"role": "assistant"}
                    if text_buf:
                        msg["content"] = "\n".join(text_buf)
                    else:
                        msg["content"] = None  # no empty-string content when only tool_calls
                    if tool_calls:
                        msg["tool_calls"] = tool_calls
                    out.append(msg)
                continue

            if role == "user":
                text_parts: List[Dict[str, Any]] = []
                tool_msgs: List[Dict[str, Any]] = []
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
                                tool_text = json.dumps(tcontent, ensure_ascii=False, sort_keys=True)
                            except Exception as e:
                                raise RuntimeError(f"FATAL: Unserializable tool_result.content: {e}")
                        # Emit tool result; if missing id, keep but mark unknown to avoid silent drop
                        tool_msgs.append({
                            "role": "tool",
                            "tool_call_id": str(tcid) if tcid else "unknown",
                            "content": tool_text or "",
                        })
                # Order: tool messages first (to mirror CCR), then user text (if any)
                out.extend([tm for tm in tool_msgs if (tm.get("content") or tm.get("tool_call_id"))])
                txt = _join_text_parts(text_parts)
                if txt.strip():
                    out.append({"role": "user", "content": txt})
                continue

            # Ignore any other roles or system lists here
            continue

    return out


def build_grader_prompt(
    prefix_messages: List[Dict[str, Any]],
    raw_bad_branch: List[Dict[str, Any]],
    raw_new_asst_obj: Dict[str, Any],
) -> List[Dict[str, Any]]:
    sys = {
        "role": "system",
        "content": (
            "You are an evaluator of AI coding assistants.\n\n"
            "You will be given a past conversation between user and an AI coding assistant."
            " The conversation ends with a turn where assistant's next action or response was bad quality, and user"
            " marked that by the marker token '<bad>' in their subsequent message along with some explanation of"
            " what assistant did wrong. You will be given a counterfactual NEW alternative response that assistant"
            " could have sent or immediate next action assistant could have taken instead of the bad actions."
            " Your task is to evaluate whether the alternative action/response would address the failure described in the user complaint."
            " Use the rubric: 1=worse/still bad; 2=minor/no improvement; 3=partially improved;"
            " 4=mostly fixed; 5=completely fixed.\n\n"
            "Read the conversation for context, read the original bad branch and the new assistant action/response,"
            " and use the 'grade' tool to return a 1–5 score of the new response and a rationale."
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


def grade_tool_def() -> Dict[str, Any]:
    return {
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


def parse_grade_from_responses(resp_obj) -> Dict[str, Any]:
    data = resp_obj if isinstance(resp_obj, dict) else resp_obj.model_dump()
    out = data.get("output", []) or []
    for item in out:
        if item.get("type") == "function_call" and item.get("name") == "grade":
            args_str = item.get("arguments", "{}")
            return json.loads(args_str)
    raise RuntimeError("No grade tool call in responses output")


async def run_eval(
    template_path: Path,
    base_out: Optional[Path],
    n_limit: Optional[int] = None,
    concurrency: int = 32,
):
    base = base_out if base_out else DEFAULT_BASE
    OUT_DIR = base / f"run-{int(time.time())}"
    SAMPLES_OUT = OUT_DIR / "samples.jsonl"
    GRADES_OUT = OUT_DIR / "grades.jsonl"
    SUMMARY_OUT = OUT_DIR / "summary.json"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # copy template in
    try:
        shutil.copyfile(template_path, OUT_DIR / "template.txt")
    except Exception:
        pass
    dataset = await read_dataset()
    total = len(dataset)
    if n_limit is not None:
        dataset = dataset[: max(0, int(n_limit))]
    selected = len(dataset)
    print(json.dumps({"event":"startup","dataset_path": str(DATASET_PATH), "total": total, "selected": selected}))

    progress_path = OUT_DIR / "progress.jsonl"
    counters = {
        "processed": 0,
        "skipped_input_tokens": 0,
        "sampler_errors": 0,
        "grader_errors": 0,
    }

    client = AsyncOpenAI(api_key=OPENAI_KEY, base_url=OPENAI_BASE) if OPENAI_BASE else AsyncOpenAI(api_key=OPENAI_KEY)
    sem = asyncio.Semaphore(max(1, int(concurrency)))

    async def process(item: Sample) -> Tuple[Optional[dict], Optional[dict]]:
        async with sem:
            print(json.dumps({"event":"process_start","cid": item.correlation_id}))
            # 1) Rewrite system via JS apply script
            sys_text = flatten_system_string(item.anthropic_request.get("system"))
            new_sys = rewrite_system_with_template(sys_text, template_path)
            # 2) Build OpenAI sampling request at the point BEFORE the bad assistant turn
            msgs = item.anthropic_request.get("messages", [])
            complaint_idx = len(msgs) - 1
            # find preceding assistant turn (skip non-assistant items between)
            prev_asst_idx = None
            for i in range(complaint_idx - 1, -1, -1):
                if msgs[i].get("role") == "assistant":
                    prev_asst_idx = i
                    break
            if prev_asst_idx is None:
                with progress_path.open("a", encoding="utf-8") as pg:
                    pg.write(json.dumps({"correlation_id": item.correlation_id, "status": "no_prev_assistant"}) + "\n")
                return None, None
            context_body = {"messages": msgs[:prev_asst_idx]}
            oai_messages = anthro_to_openai_messages(context_body, new_sys)
            in_tokens = tokens_for_chat_messages(oai_messages)
            print(json.dumps({"event":"sampler_tokens","cid": item.correlation_id, "in_tokens": in_tokens}))
            if in_tokens > MAX_INPUT_TOKENS:
                counters["skipped_input_tokens"] += 1
                with progress_path.open("a", encoding="utf-8") as pg:
                    pg.write(
                        json.dumps(
                            {
                                "correlation_id": item.correlation_id,
                                "status": "skipped_input_too_large",
                                "input_tokens": in_tokens,
                            }
                        )
                        + "\n"
                    )
                return None, None
            samp_max = max(
                1, min(PER_OUTPUT_CAP, MAX_TOTAL_TOKENS - in_tokens - SAFETY_TOKENS)
            )
            tools_param = item.anthropic_request.get("tools")
            def _map_tools_for_chat(tools_val):
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
                        ct = _to_chat_tool(t)
                        if ct:
                            out.append(ct)
                return out or None
            chat_tools = _map_tools_for_chat(tools_param)
            samp_req = {
                "model": SAMPLER_MODEL,
                "messages": oai_messages,
                "tools": chat_tools,
                "tool_choice": "auto",
                "parallel_tool_calls": True,
                "max_completion_tokens": samp_max,
            }
            # 3) Send to sampler model
            try:
                # Use the same request dict we persist (no duplication)
                samp = await client.chat.completions.create(**{k: v for k, v in samp_req.items() if v is not None})
            except Exception as e:
                counters["sampler_errors"] += 1
                msg = json.dumps(
                    {
                        "correlation_id": item.correlation_id,
                        "status": "sampler_error",
                        "error": str(e),
                    }
                )
                with progress_path.open("a", encoding="utf-8") as pg:
                    pg.write(msg + "\n")
                sys.stderr.write(msg + "\n")
                sys.stderr.flush()
                return None, None
            new_asst_obj = samp.choices[0].message

            # 4) Build grading inputs
            msgs = item.anthropic_request.get("messages", [])
            last = msgs[-1]
            raw_bad_user_obj = last
            raw_new_asst_obj = new_asst_obj.model_dump()
            raw_bad_asst_obj: Dict[str, Any] = {}
            if len(msgs) >= 2 and msgs[-2].get("role") == "assistant":
                raw_bad_asst_obj = msgs[-2]
            base_prefix = msgs[:-2] if len(msgs) >= 2 else []
            base_prefix = [m for m in base_prefix if m.get("role") != "system"]
            # Compute bad branch (inclusive of complaint)
            complaint_idx = len(msgs) - 1
            raw_bad_branch = msgs[prev_asst_idx:complaint_idx + 1]
            # Keep first 5 and last 5; truncate middle to fit token budget
            first = base_prefix[:5]
            last = base_prefix[-5:] if len(base_prefix) > 5 else []
            middle = base_prefix[5: len(base_prefix) - len(last)] if len(base_prefix) > 10 else []
            # Build a provisional grader input to compute tokens; start from minimal
            def mk_grader_input(prefix_subset: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
                gm = build_grader_prompt(
                    prefix_subset,
                    raw_bad_branch,
                    raw_new_asst_obj,
                )
                return [
                    {"role": "system", "content": gm[0]["content"]},
                    {"role": "user", "content": gm[1]["content"]},
                ]
            prefix_msgs = first + []  # start with first only
            gi = mk_grader_input(prefix_msgs + last)
            tok = tokens_for_chat_messages(gi)
            # Greedily add middle messages until we hit budget
            added = 0
            for m in middle:
                trial = mk_grader_input(prefix_msgs + [m] + last)
                trial_tok = tokens_for_chat_messages(trial)
                if trial_tok <= TARGET_PREFIX_TOKENS:
                    prefix_msgs.append(m)
                    gi = trial
                    tok = trial_tok
                    added += 1
                else:
                    break
            # Attach tail (already accounted in gi)
            prefix_msgs = prefix_msgs + last
            # Log truncation info
            with progress_path.open("a", encoding="utf-8") as pg:
                pg.write(json.dumps({
                    "correlation_id": item.correlation_id,
                    "status": "grader_prefix_built",
                    "prefix_counts": {"total": len(base_prefix), "kept_first": len(first), "kept_last": len(last), "added_middle": added},
                    "token_estimate": tok
                }) + "\n")
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
                with progress_path.open("a", encoding="utf-8") as pg:
                    pg.write(
                        json.dumps(
                            {
                                "correlation_id": item.correlation_id,
                                "status": "grader_skipped_input_too_large",
                                "input_tokens": in_tokens_g,
                            }
                        )
                        + "\n"
                    )
                return None, None
            grade_max = max(
                1,
                min(PER_OUTPUT_CAP, MAX_TOTAL_TOKENS - in_tokens_g - SAFETY_TOKENS),
            )
            grade_req = {
                "model": GRADER_MODEL,
                "input": grader_input,
                "tools": [grade_tool_def()],
                "tool_choice": {"type": "function", "name": "grade"},
                "parallel_tool_calls": False,
                "max_output_tokens": grade_max,
            }
            try:
                grade = await client.responses.create(**grade_req)
            except Exception as e:
                counters["grader_errors"] += 1
                msg = json.dumps(
                    {
                        "correlation_id": item.correlation_id,
                        "status": "grader_error",
                        "error": str(e),
                    }
                )
                with progress_path.open("a", encoding="utf-8") as pg:
                    pg.write(msg + "\n")
                sys.stderr.write(msg + "\n")
                sys.stderr.flush()
                return None, None
            # Validate grade parse
            try:
                _ = parse_grade_from_responses(grade)
            except Exception as e:
                counters["grader_errors"] += 1
                msg = json.dumps(
                    {
                        "correlation_id": item.correlation_id,
                        "status": "grader_parse_error",
                        "error": str(e),
                    }
                )
                with progress_path.open("a", encoding="utf-8") as pg:
                    pg.write(msg + "\n")
                sys.stderr.write(msg + "\n")
                sys.stderr.flush()
                return None, None

            # Return combined records for saving
            return (
                {
                    "request": samp_req,
                    "response": samp.model_dump(),
                    "new_assistant_message": new_asst_obj.model_dump(),
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
    print(json.dumps({"event": "tasks_build_start", "selected": selected}))
    tasks = [process(item) for item in dataset]
    print(json.dumps({"event": "tasks_built", "count": len(tasks)}))

    scores: List[float] = []
    # Secondary metrics: tooling usage
    tool_stats = {
        "total_samples": 0,
        "text_only": 0,
        "with_tools": 0,
        "function_counts": {},  # name -> count of tool calls
    }
    with (
        SAMPLES_OUT.open("w", encoding="utf-8") as s_out,
        GRADES_OUT.open("w", encoding="utf-8") as g_out,
    ):
        print(json.dumps({"event": "as_completed_start", "count": len(tasks)}))
        for fut in asyncio.as_completed(tasks):
            samp_rec, grade_rec = await fut
            if samp_rec:
                s_out.write(json.dumps(samp_rec, ensure_ascii=False, sort_keys=True) + "\n")
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
            if grade_rec:
                g_out.write(json.dumps(grade_rec, ensure_ascii=False, sort_keys=True) + "\n")
                try:
                    parsed = parse_grade_from_responses(grade_rec["response"])  # type: ignore[index]
                    score = float(parsed.get("score", 0))
                    scores.append(score)
                    counters["processed"] += 1
                    print(json.dumps({"event": "grade_parsed", "cid": grade_rec.get("correlation_id"), "score": score}))
                except Exception as e:
                    counters["grader_errors"] += 1
                    with progress_path.open("a", encoding="utf-8") as pg:
                        pg.write(
                            json.dumps(
                                {"status": "aggregate_parse_error", "error": str(e)}
                            )
                            + "\n"
                        )

    # Compute mean and 95% CI (normal approx)
    import math

    mean = sum(scores) / len(scores) if scores else 0.0
    var = (
        sum((x - mean) ** 2 for x in scores) / (len(scores) - 1)
        if len(scores) > 1
        else 0.0
    )
    se = math.sqrt(var / len(scores)) if len(scores) > 0 else 0.0
    ci95 = 1.96 * se
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    lcb = mean - ci95
    ucb = mean + ci95
    # Compute secondary metrics
    total_samples = tool_stats["total_samples"] or 0
    total_tool_calls = sum(tool_stats["function_counts"].values()) if tool_stats["function_counts"] else 0
    function_pct = {
        k: (v / total_tool_calls) if total_tool_calls > 0 else 0.0
        for k, v in tool_stats["function_counts"].items()
    }
    summary = {
        "n": len(scores),
        "mean": mean,
        "ci95": ci95,
        "lcb": lcb,
        "ucb": ucb,
        "counters": counters,
        "tooling": {
            "total_samples": total_samples,
            "text_only_pct": (tool_stats["text_only"] / total_samples) if total_samples > 0 else 0.0,
            "with_tools_pct": (tool_stats["with_tools"] / total_samples) if total_samples > 0 else 0.0,
            "function_counts": tool_stats["function_counts"],
            "function_pct": function_pct,
        },
    }
    with SUMMARY_OUT.open("w", encoding="utf-8") as f:
        json.dump(summary, f, sort_keys=True)
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    args = parse_args()
    base_out = Path(args.out_dir) if args.out_dir else None
    asyncio.run(run_eval(Path(args.template), base_out, args.n, args.concurrency))
