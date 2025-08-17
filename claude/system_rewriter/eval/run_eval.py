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

import aiohttp
import tiktoken  # type: ignore

# Config
DATASET_PATH = Path(__file__).parent / "data" / "dataset.jsonl"
DEFAULT_BASE = Path(__file__).parent / "runs"
OUT_DIR = None  # set at runtime
SAMPLES_OUT = None
GRADES_OUT = None
SUMMARY_OUT = None
DEFAULT_CONCURRENCY = 32
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

OPENAI_BASE = os.environ.get("OPENAI_BASE", "https://api.openai.com/v1")
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
HEADERS = {"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"}


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


async def openai_chat(
    session: aiohttp.ClientSession,
    messages: List[Dict[str, Any]],
    model: str,
    max_tokens: int,
) -> Dict[str, Any]:
    url = f"{OPENAI_BASE}/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": max(1, max_tokens),
        "stream": False,
    }
    async with session.post(url, headers=HEADERS, json=payload, timeout=None) as resp:
        text = await resp.text()
        if resp.status >= 400:
            raise RuntimeError(f"chat error {resp.status}: {text}")
        return json.loads(text)


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
    # Convert Anthropic-style to OpenAI chat format using provided system text
    out: List[Dict[str, Any]] = []
    if new_system_text:
        out.append({"role": "system", "content": new_system_text})
    # messages
    for m in body.get("messages", []):
        role = m.get("role")
        content = m.get("content")
        if isinstance(content, str):
            out.append({"role": role, "content": content})
        elif isinstance(content, list):
            texts: List[str] = []
            for part in content:
                if (
                    isinstance(part, dict)
                    and part.get("type") == "text"
                    and isinstance(part.get("text"), str)
                ):
                    texts.append(part["text"])
            out.append({"role": role, "content": "\n".join(texts)})
    return out


def build_grader_prompt(
    prefix_messages: List[Dict[str, Any]],
    raw_bad_asst_obj: Dict[str, Any],
    raw_bad_user_obj: Dict[str, Any],
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
            "Read the conversation for context, read the original and new assistant action/response and user's complaint,"
            " and use the 'grade' tool to return a 1–5 score of the new response and a rationale."
        ),
    }
    user = {
        "role": "user",
        "content": (
            "The following is a past conversation between user and an AI coding assistant:\n"
            + json.dumps(prefix_messages, ensure_ascii=False)
            + "\n\n"
            + "After the prefix above, assistant gave the following bad action or response:\n"
            + json.dumps(raw_bad_asst_obj or {})
            + "\n\n"
            + "In response to the reply, user gave the following complaint:\n"
            + json.dumps(raw_bad_user_obj or {})
            + "\n\n"
            + "Evaluate if the following assistant action or response would be better than the original one:\n"
            + json.dumps(raw_new_asst_obj or {})
        ),
    }
    return [sys, user]


async def openai_responses(
    session: aiohttp.ClientSession, payload: Dict[str, Any]
) -> Dict[str, Any]:
    url = f"{OPENAI_BASE}/responses"
    async with session.post(url, headers=HEADERS, json=payload, timeout=None) as resp:
        text = await resp.text()
        if resp.status >= 400:
            raise RuntimeError(f"responses error {resp.status}: {text}")
        return json.loads(text)


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


def parse_grade_from_responses(resp: Dict[str, Any]) -> Dict[str, Any]:
    out = resp.get("output", []) or []
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
    global OUT_DIR, SAMPLES_OUT, GRADES_OUT, SUMMARY_OUT
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
    if n_limit is not None:
        dataset = dataset[: max(0, int(n_limit))]

    progress_path = OUT_DIR / "progress.jsonl"
    counters = {
        "processed": 0,
        "skipped_input_tokens": 0,
        "sampler_errors": 0,
        "grader_errors": 0,
    }

    async with aiohttp.ClientSession() as session:
        sem = asyncio.Semaphore(max(1, int(concurrency)))

        async def process(item: Sample) -> Tuple[Optional[dict], Optional[dict]]:
            async with sem:
                # 1) Rewrite system via JS apply script
                sys_text = flatten_system_string(item.anthropic_request.get("system"))
                new_sys = rewrite_system_with_template(sys_text, template_path)
                # 2) Build OpenAI sampling request
                oai_messages = anthro_to_openai_messages(
                    item.anthropic_request, new_sys
                )
                in_tokens = tokens_for_chat_messages(oai_messages)
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
                samp_req = {
                    "model": SAMPLER_MODEL,
                    "messages": oai_messages,
                    "max_completion_tokens": samp_max,
                }
                # 3) Send to sampler model
                try:
                    samp = await openai_chat(
                        session, oai_messages, SAMPLER_MODEL, samp_max
                    )
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
                new_asst_msg = samp.get("choices", [{}])[0].get("message")
                if not isinstance(new_asst_msg, dict):
                    raise RuntimeError("sampler returned no message object")

                # 4) Build grading inputs
                msgs = item.anthropic_request.get("messages", [])
                last = msgs[-1]
                raw_bad_asst_obj: Dict[str, Any] = {}
                if len(msgs) >= 2 and msgs[-2].get("role") == "assistant":
                    raw_bad_asst_obj = msgs[-2]
                base_prefix = msgs[:-2] if len(msgs) >= 2 else []
                base_prefix = [m for m in base_prefix if m.get("role") != "system"]
                # Keep first 5 and last 5; truncate middle to fit token budget
                first = base_prefix[:5]
                last = base_prefix[-5:] if len(base_prefix) > 5 else []
                middle = base_prefix[5: len(base_prefix) - len(last)] if len(base_prefix) > 10 else []
                # Build a provisional grader input to compute tokens; start from minimal
                def mk_grader_input(prefix_subset: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
                    gm = build_grader_prompt(
                        prefix_subset,
                        raw_bad_asst_obj,
                        raw_bad_user_obj,
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
                raw_new_asst_obj = new_asst_msg
                raw_bad_user_obj = last
                grader_messages = build_grader_prompt(
                    prefix_msgs,
                    raw_bad_asst_obj,
                    raw_bad_user_obj,
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
                    grade = await openai_responses(session, grade_req)
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
                        "response": samp,
                        "new_assistant_message": new_asst_msg,
                        "correlation_id": item.correlation_id,
                        "timestamp": item.timestamp,
                        "anthropic_request": item.anthropic_request,
                    },
                    {
                        "request": grade_req,
                        "response": grade,
                        "correlation_id": item.correlation_id,
                        "timestamp": item.timestamp,
                    },
                )

        tasks = [process(item) for item in dataset]

        scores: List[float] = []
        with (
            SAMPLES_OUT.open("w", encoding="utf-8") as s_out,
            GRADES_OUT.open("w", encoding="utf-8") as g_out,
        ):
            for fut in asyncio.as_completed(tasks):
                samp_rec, grade_rec = await fut
                if samp_rec:
                    s_out.write(json.dumps(samp_rec, ensure_ascii=False) + "\n")
                if grade_rec:
                    g_out.write(json.dumps(grade_rec, ensure_ascii=False) + "\n")
                    try:
                        parsed = parse_grade_from_responses(grade_rec["response"])  # type: ignore[index]
                        score = float(parsed.get("score", 0))
                        scores.append(score)
                        counters["processed"] += 1
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
        summary = {
            "n": len(scores),
            "mean": mean,
            "ci95": ci95,
            "lcb": lcb,
            "ucb": ucb,
            "counters": counters,
        }
        with SUMMARY_OUT.open("w", encoding="utf-8") as f:
            json.dump(summary, f)
        print(json.dumps(summary))


if __name__ == "__main__":
    args = parse_args()
    base_out = Path(args.out_dir) if args.out_dir else None
    asyncio.run(run_eval(Path(args.template), base_out, args.n, args.concurrency))
