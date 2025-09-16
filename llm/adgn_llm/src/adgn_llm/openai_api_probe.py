#!/usr/bin/env python3
"""Probe OpenAI models via Responses and Chat APIs.

Usage:
    python /Users/mpokorny/code/ducktape/llm/adgn_llm/src/adgn_llm/openai_api_probe.py \
        [--sample N] [--concurrency C] [--repeats R] [--max-qps Q]

The script performs the following steps:
    1. Lists all model IDs from the OpenAI API asynchronously.
    2. Filters out models by family rules (regex-based heuristics).
    3. Optionally subsamples the remaining list.
    4. For each repeat, iterates models in priority order and schedules two
       probes per model (Responses and Chat), honoring global concurrency and
       optional QPS limiting.
    5. Streams a live table with successes first, and finally prints a summary
       of failures and legend of error codes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import sys
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, Final, Sequence, cast

from aiolimiter import AsyncLimiter
from openai import AsyncOpenAI
from openai._exceptions import APIStatusError
from openai.types.responses.function_tool_param import FunctionToolParam
from openai.types.responses.tool_choice_function_param import ToolChoiceFunctionParam
from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.table import Table


@dataclass(frozen=True)
class ProbeResult:
    model_id: str
    ok: bool
    content: str | None = None
    exc: BaseException | None = None
    latency_s: float | None = None


@dataclass(frozen=True)
class CallResult:
    content: str | None
    exc: BaseException | None
    latency_s: float | None

    @property
    def ok(self) -> bool:
        return self.exc is None


@dataclass(frozen=True)
class ProbeRun:
    model_id: str
    calls: list[CallResult]

    @property
    def ok(self) -> bool:
        return any(c.ok for c in self.calls)

    @property
    def avg_latency_s(self) -> float | None:
        vals = [c.latency_s for c in self.calls if c.ok and c.latency_s is not None]
        return (sum(vals) / len(vals)) if vals else None

    @property
    def first_error(self) -> BaseException | None:
        for c in self.calls:
            if not c.ok:
                return c.exc
        return None

    @property
    def success_snippet(self) -> str | None:
        for c in self.calls:
            if c.ok and c.content:
                return c.content
        return None


@dataclass(frozen=True)
class ModelProbe:
    model_id: str
    responses: ProbeRun
    chat: ProbeRun

    @property
    def any_ok(self) -> bool:
        return self.responses.ok or self.chat.ok


@dataclass(frozen=True)
class ProbeSpec:
    name: str
    create: Callable[[AsyncOpenAI, str], Awaitable[Any]]
    snippet: Callable[[Any], str]


_GET_TIME_NAME: Final[str] = "get_time"
PROMPT = "What's the time in Prague? Use get_time."
TOOL_FUNCTION = {
    "name": _GET_TIME_NAME,
    "description": "Get current time for a city",
    "parameters": {
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
    },
}
REQUEST_TIMEOUT = 10

# Typed tool shapes for Responses API (mypy-safe) without duplicating TOOL_FUNCTION
_base_tool: dict[str, object] = {"type": "function", "strict": True}
_base_tool.update(TOOL_FUNCTION)  # merge name/description/parameters
GET_TIME_TOOL: FunctionToolParam = cast(FunctionToolParam, _base_tool)
GET_TIME_TOOL_CHOICE: ToolChoiceFunctionParam = {
    "type": "function",
    "name": _GET_TIME_NAME,
}


# ---------- Probe spec creators ----------
# Tool configs per API (Responses vs Chat)
async def _create_responses(c: AsyncOpenAI, m: str):
    return await c.responses.create(
        model=m,
        input=PROMPT,
        tools=[GET_TIME_TOOL],
        tool_choice=GET_TIME_TOOL_CHOICE,
        max_output_tokens=20,
    )


async def _create_chat(c: AsyncOpenAI, m: str):
    # Keep runtime-correct shapes but avoid heavy typed imports; annotate as Any for mypy

    messages: Any = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": PROMPT},
    ]
    tools: Any = [{"type": "function", "function": TOOL_FUNCTION}]
    tool_choice: Any = {"type": "function", "function": {"name": _GET_TIME_NAME}}
    return await c.chat.completions.create(
        model=m,
        messages=messages,
        tools=tools,
        tool_choice=tool_choice,
        max_completion_tokens=20,
    )


async def _probe_once(
    client: AsyncOpenAI,
    *,
    model_id: str,
    spec: ProbeSpec,
    limiter: AsyncLimiter,
) -> ProbeResult:
    try:
        async with limiter:
            t0 = time.perf_counter()  # measure pure API latency, not queueing time
            resp = await asyncio.wait_for(spec.create(client, model_id), timeout=REQUEST_TIMEOUT)
        dt = time.perf_counter() - t0
        snippet = spec.snippet(resp)
        return ProbeResult(model_id=model_id, ok=True, content=snippet, latency_s=dt)
    except Exception as exc:
        return ProbeResult(model_id=model_id, ok=False, exc=exc)


# ---------- Filtering rules -------------------------------------------------


# Model family heuristic
class Family(str, Enum):
    LEGACY_ENGINES = "legacy-engines"
    GPT_3 = "gpt-3"
    GPT_4O = "gpt-4o"
    GPT_41_MINI_NANO = "gpt-4.1-mini-nano"
    GPT_5_MINI_NANO = "gpt-5-mini-nano"
    O_MINI = "o-mini"
    RM_MODELS = "rm-models"
    D12_D16 = "d12-d16"
    # Kept/classifiable families
    GPT_5 = "gpt-5"
    O3 = "o3"
    O4_MINI = "o4-mini"
    O1 = "o1"
    GPT_41 = "gpt-4.1"
    OTHER = "other"


FAMILY_RULES: dict[Family, str] = {
    # Dropped families (filtered out)
    Family.LEGACY_ENGINES: r"\b(ada|curie|babbage|davinci)\b",
    Family.GPT_3: r"\bgpt[-_]?3(\b|[.-])",
    Family.GPT_4O: r"(?<![a-z0-9])gpt[-_]?4o(?![a-z0-9])",
    Family.GPT_41_MINI_NANO: r"\bgpt[-_]?4\.1-(mini|nano)\b",
    Family.GPT_5_MINI_NANO: r"\bgpt[-_]?5-(mini|nano)\b",
    Family.O_MINI: r"\bo[13]-mini\b",
    Family.RM_MODELS: r"-rm-",
    Family.D12_D16: r"\b(d1[26])\b",
    # Kept/classifiable families
    Family.GPT_5: r"^gpt[-_]?5(?!-(mini|nano))",
    Family.O3: r"^o3(?!-mini)",
    Family.O4_MINI: r"^o4-mini",
    Family.O1: r"^o1(?!-mini)",
    Family.GPT_41: r"^gpt[-_]?4\.1(?!-(mini|nano))",
}
FAMILY_RES = {fam: re.compile(pattern, re.I) for fam, pattern in FAMILY_RULES.items()}
FAMILY_DROP: set[Family] = {
    Family.LEGACY_ENGINES,
    Family.GPT_3,
    Family.GPT_4O,
    Family.GPT_41_MINI_NANO,
    Family.GPT_5_MINI_NANO,
    Family.O_MINI,
    Family.RM_MODELS,
    Family.D12_D16,
}


def family_of(mid: str) -> Family:
    for fam, rx in FAMILY_RES.items():
        if rx.search(mid):
            return fam
    return Family.OTHER


def is_excluded(mid: str) -> bool:
    return family_of(mid) in FAMILY_DROP


# ---------- Error classifier rules (table-driven) ----------
class ErrorCode(str, Enum):
    MISSING_TOOLS_NAME = "MISSING-TOOLS-NAME"
    RATE_LIMIT = "RATE-LIMIT"
    TOO_LARGE = "TOO-LARGE"
    NO_CAP = "NO-CAP"
    RESP_ONLY = "RESP-ONLY"
    NOT_CHAT = "NOT-CHAT"
    TIMEOUT = "TIMEOUT"
    INVALID_OUTPUT = "INVALID-OUTPUT"
    SERVER_ERROR = "SERVER-ERROR"
    NOT_FOUND = "NOT-FOUND"
    TOOLS_UNSUPPORTED = "TOOLS-UNSUPPORTED"
    FORBIDDEN = "FORBIDDEN"
    AUDIO_REQUIRED = "AUDIO-REQUIRED"
    INVALID_HEADERS = "INVALID-HEADERS"
    INVALID_REQUEST = "INVALID-REQUEST"
    TTS_MODEL = "TTS-MODEL"
    OTHER = "OTHER"


ERROR_RULES: dict[ErrorCode, tuple[str, Callable[[str], bool]]] = {
    ErrorCode.MISSING_TOOLS_NAME: (
        "Missing required parameter: tools[0].name (malformed tool spec)",
        lambda m: "missing required parameter" in m and "tools" in m,
    ),
    ErrorCode.RATE_LIMIT: (
        "Rate limit reached",
        lambda m: "rate limit" in m or "too many requests" in m,
    ),
    ErrorCode.TOO_LARGE: (
        "Request too large for model/limits",
        lambda m: "request too large" in m or "payload too large" in m,
    ),
    ErrorCode.NO_CAP: (
        "No available capacity for the model",
        lambda m: "no available capacity" in m,
    ),
    ErrorCode.RESP_ONLY: (
        "Model is only supported in v1/responses, not v1/chat/completions",
        lambda m: "only supported in v1/responses" in m or "require responses" in m,
    ),
    ErrorCode.NOT_CHAT: (
        "Not a chat model; use v1/completions or v1/responses",
        lambda m: "not a chat model" in m and "v1/chat/completions" in m,
    ),
    ErrorCode.TIMEOUT: (
        "Request timed out (10s)",
        lambda m: "timeout" in m,
    ),
    ErrorCode.INVALID_OUTPUT: (
        "Model produced invalid output",
        lambda m: "invalid output" in m or "produced invalid output" in m,
    ),
    ErrorCode.SERVER_ERROR: (
        "Server error while processing request",
        lambda m: "server had an error" in m or "an error occurred while processing" in m,
    ),
    ErrorCode.NOT_FOUND: (
        "Model does not exist or access denied",
        lambda m: "does not exist" in m or "do not have access" in m or "model not found" in m or "not available" in m,
    ),
    ErrorCode.TOOLS_UNSUPPORTED: (
        "Tools/function calling not supported by this model",
        lambda m: "tools is not supported" in m or "functions are not supported" in m,
    ),
    ErrorCode.FORBIDDEN: (
        "Not allowed to sample from this model",
        lambda m: "not allowed to sample" in m,
    ),
    ErrorCode.AUDIO_REQUIRED: (
        "Model requires audio input/output modality",
        lambda m: "requires" in m and "audio" in m,
    ),
    ErrorCode.INVALID_HEADERS: (
        "Invalid header configuration",
        lambda m: "invalid header configuration" in m,
    ),
    ErrorCode.INVALID_REQUEST: (
        "Invalid request; check inputs",
        lambda m: "issue with your request" in m or "invalid request" in m,
    ),
    ErrorCode.TTS_MODEL: (
        "Text-to-speech model; not supported on chat/responses",
        lambda m: "tts-" in m,
    ),
}

# ---------- Async helpers ----------------------------------------------------


def _squeeze_one_line(text: str, max_len: int = 120) -> str:
    s = " ".join(str(text).split())
    return s if len(s) <= max_len else s[: max_len - 1] + "…"


def _tool_ok_if_expected(name: str | None, args: object) -> bool:
    """Return True if tool call matches our expected probe signature.
    Accepts either dict args or JSON string; supports get_time.
    """
    if name != "get_time":
        return False
    args_obj = args
    if isinstance(args, str):
        # Let exceptions bubble up if malformed JSON – indicates misuse
        args_obj = json.loads(args)
    return isinstance(args_obj, dict) and args_obj == {"city": "Prague"}


def _snippet_from_responses(resp) -> str:
    if txt := resp.output_text:
        return _squeeze_one_line(txt)
    # Fallback: inspect model_dump for output blocks and tool/function calls
    data = resp.model_dump(exclude_none=True)
    outputs = data.get("output", []) or []
    for item in outputs:
        typ = item.get("type")
        name: str | None = None
        args = None
        if typ == "function_call":
            fc = item.get("function_call")
            if isinstance(fc, dict) and fc:
                name = fc.get("name")
                args = fc.get("arguments")
            else:
                # Some Responses payloads expose name/arguments at top-level
                name = item.get("name")
                args = item.get("arguments")
        elif typ == "tool_call":
            tc = item.get("tool_call") or {}
            fn = tc.get("function") or {}
            name = fn.get("name") or tc.get("name")
            args = fn.get("arguments") if "arguments" in fn else tc.get("arguments")
        elif typ == "output_text":
            text = item.get("text") or ""
            if text:
                return "✓ " + _squeeze_one_line(text)
        if name:
            if _tool_ok_if_expected(name, args):
                return "✓ tool OK"
            if isinstance(args, (dict, list)):
                arg_s = json.dumps(args, separators=(",", ":"))
            else:
                arg_s = str(args) if args is not None else ""
            return "✓ " + _squeeze_one_line(f"{name}({arg_s})")
    return "✓"


def _snippet_from_chat(resp) -> str:
    data = resp.model_dump(exclude_none=True)
    choices = data.get("choices", []) or []
    if choices:
        msg = choices[0].get("message") or choices[0].get("delta") or {}
        if msg.get("tool_calls"):
            tc = msg["tool_calls"][0]
            fn = tc.get("function") or {}
            name = fn.get("name")
            args = fn.get("arguments")
            if _tool_ok_if_expected(name, args):
                return "tool OK"
            snippet = f"{name}({args})"
            return _squeeze_one_line(snippet)
        if isinstance(msg.get("content"), str):
            return _squeeze_one_line(msg.get("content", ""))
    # Fallback to attribute API (no swallowing)
    content = resp.choices[0].message.content if resp.choices else None
    if content:
        return "✓ " + _squeeze_one_line(str(content))
    return "✓"


# ---------- Main -------------------------------------------------------------


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:  # noqa: D401
    """Minimal CLI."""
    parser = argparse.ArgumentParser(description="Filter and test OpenAI models")
    parser.add_argument(
        "--sample",
        type=int,
        default=0,
        help="Randomly sample N models (0 = use all)",
    )
    parser.add_argument(
        "--concurrency",
        "-c",
        type=int,
        default=128,
        help="Max concurrent requests",
    )
    parser.add_argument(
        "--repeats",
        "-r",
        type=int,
        default=5,
        help="Repeats per probe per model (default: 5)",
    )
    parser.add_argument(
        "--max-qps",
        "-q",
        type=float,
        default=0.3,
        help="Global max QPS",
    )
    return parser.parse_args(argv)


async def main() -> None:
    args = parse_args()
    # Create a single limiter for the whole run. No disable path; coerce to >= 1e-6.
    qps = float(args.max_qps)
    if qps <= 0:
        qps = 1.0
    # Support fractional QPS by adjusting the time window
    if qps >= 1.0:
        limiter = AsyncLimiter(int(qps), 1.0)
    else:
        limiter = AsyncLimiter(1, 1.0 / qps)

    async_client = AsyncOpenAI()
    print("Fetching model list …", file=sys.stderr)
    resp = await async_client.models.list()
    model_ids = [m.id for m in resp.data]
    print(f"Total models from API: {len(model_ids)}", file=sys.stderr)

    # Filtering --------------------------------------------------------------
    filtered = [mid for mid in model_ids if not is_excluded(mid)]
    print(f"After filtering rules: {len(filtered)}", file=sys.stderr)

    # Optional sampling ------------------------------------------------------
    if args.sample and args.sample < len(filtered):
        filtered = random.sample(filtered, args.sample)
        print(f"Sub-sampled to {len(filtered)} models (random)", file=sys.stderr)

    # Build probe specs now that snippet functions are defined
    RESPONSES_SPEC = ProbeSpec(name="responses", create=_create_responses, snippet=_snippet_from_responses)
    CHAT_SPEC = ProbeSpec(name="chat", create=_create_chat, snippet=_snippet_from_chat)

    sem = asyncio.Semaphore(max(args.concurrency, 1))

    async def run_one(spec: ProbeSpec, mid: str):
        async with sem:
            res = await _probe_once(
                async_client,
                model_id=mid,
                spec=spec,
                limiter=limiter,
            )
        return spec.name, mid, res

    # Repeats per probe per model (CLI override)
    REPEATS = max(int(args.repeats), 1)

    # Build prioritized order using family heuristic
    FAMILY_ORDER: list[Family] = [
        Family.GPT_5,
        Family.O3,
        Family.O4_MINI,
        Family.O1,
        Family.GPT_41,
    ]

    def priority_index(mid: str) -> int:
        fam = family_of(mid)
        try:
            return FAMILY_ORDER.index(fam)
        except ValueError:
            return len(FAMILY_ORDER)

    def sort_priority(mid: str) -> tuple[int, str]:
        return (priority_index(mid), mid)

    prioritized = sorted(filtered, key=sort_priority)

    tasks = []
    for _ in range(REPEATS):
        for mid in prioritized:
            tasks.append(asyncio.create_task(run_one(RESPONSES_SPEC, mid)))
            tasks.append(asyncio.create_task(run_one(CHAT_SPEC, mid)))

    oks: list[ModelProbe] = []
    fails: list[ModelProbe] = []
    total_models = len(filtered)
    completed_models = 0
    acc: dict[str, dict[str, list[CallResult]]] = {mid: {"responses": [], "chat": []} for mid in filtered}

    console = Console()

    def classify(mid: str) -> str:
        return family_of(mid).value

    INF = 1e9

    def _avg_lat(obj) -> float | None:
        if isinstance(obj, ProbeRun):
            return obj.avg_latency_s
        return obj.latency_s

    def _std_lat(obj) -> float | None:
        if isinstance(obj, ProbeRun):
            vals = [c.latency_s for c in obj.calls if c.ok and c.latency_s is not None]
            if len(vals) >= 2:
                m = sum(vals) / len(vals)
                var = sum((x - m) ** 2 for x in vals) / len(vals)
                return var**0.5
            return 0.0 if len(vals) == 1 else None
        return None

    def make_results_table(
        title: str,
        *,
        header_style: str = "bold magenta",
        model_ratio: int = 3,
    ) -> Table:
        table = Table(
            show_header=True,
            header_style=header_style,
            title=title,
            expand=True,
            box=box.SIMPLE,
        )
        table.add_column(
            "Model",
            overflow="ellipsis",
            no_wrap=True,
            ratio=model_ratio,
            header_style="bold",
        )
        table.add_column("Responses", overflow="ellipsis", no_wrap=True, ratio=2)
        table.add_column("Chat", overflow="ellipsis", no_wrap=True, ratio=2)
        return table

    def iter_with_break(rows, key_fn):
        if not rows:
            return []
        result = []
        for idx, row in enumerate(rows):
            curr = key_fn(row)
            nxt = key_fn(rows[idx + 1]) if idx + 1 < len(rows) else None
            result.append((row, nxt is not None and nxt != curr))
        return result

    def partials_sort_key(kind: str):
        def key(item: tuple[str, str, str]):
            mid = item[0]
            avg = _avg_lat(ProbeRun(model_id=mid, calls=acc[mid][kind])) or INF
            return (priority_index(mid), avg, mid)

        return key

    def latency_both_key(r: ModelProbe) -> float:
        vals = [v for v in (_avg_lat(r.responses), _avg_lat(r.chat)) if v is not None]
        return min(vals) if vals else INF

    def latency_resp_key(r: ModelProbe) -> float:
        v = _avg_lat(r.responses)
        return v if v is not None else INF

    def latency_chat_key(r: ModelProbe) -> float:
        v = _avg_lat(r.chat)
        return v if v is not None else INF

    def msg_from_exc(e: BaseException | None) -> str:
        if e is None:
            return ""
        if isinstance(e, APIStatusError):
            body = e.body
            msg = body.get("message") if isinstance(body, dict) and "message" in body else e.message
            return msg or repr(e)
        return str(e) or repr(e)

    def probe_snippet(p) -> str | None:
        if isinstance(p, ProbeRun):
            return p.success_snippet
        return p.content

    def probe_exc(p) -> BaseException | None:
        if isinstance(p, ProbeRun):
            return p.first_error
        return p.exc

    def ok_cell(probe) -> str:
        txt = (probe_snippet(probe) or "").removeprefix("✓ ").strip()
        cell = (
            f"[green]✓{fmt_latency(probe)}[/green]"
            if txt == "tool OK"
            else f"[green]✓ {txt}{fmt_latency(probe)}[/green]"
        )
        # Combine avg±stds when we have repeats (ProbeRun) and generic tool OK
        if isinstance(probe, ProbeRun) and txt == "tool OK":
            s = _std_lat(probe)
            avg = _avg_lat(probe)
            if avg is not None:
                cell = f"[green]✓ {avg:.1f}s[/green]"
                if s is not None:
                    cell += f" ±{s:.1f}s"
        return cell

    def err_cell(probe) -> str:
        ex = probe_exc(probe)
        if isinstance(ex, asyncio.TimeoutError):
            return f"[red]TIMEOUT{fmt_latency(probe)}[/red]"
        msg = msg_from_exc(ex)
        code, desc = classify_error(msg)
        if code != ErrorCode.OTHER:
            used_codes.setdefault(code.value, desc)
            return f"[red]{code.value}{fmt_latency(probe)}[/red]"
        return f"[red]{type(ex).__name__ if ex else ''}: {_squeeze_one_line(msg)}{fmt_latency(probe)}[/red]"

    # Reusable cell builders to dedupe rendering logic
    WAITING_CELL = "[yellow]waiting…[/yellow]"

    def _calls_for(mid: str, kind: str) -> list[CallResult]:
        return acc[mid][kind]

    def _probe_run_for(mid: str, kind: str) -> ProbeRun:
        return ProbeRun(model_id=mid, calls=_calls_for(mid, kind))

    def cell_for_kind(mid: str, kind: str) -> str:
        calls = _calls_for(mid, kind)
        if not calls:
            return WAITING_CELL
        pr = ProbeRun(model_id=mid, calls=calls)
        return ok_cell(pr) if pr.ok else err_cell(pr)

    def kind_ok(mid: str, kind: str) -> bool:
        calls = _calls_for(mid, kind)
        return bool(calls) and _probe_run_for(mid, kind).ok

    # Error classifier: short code → long description
    def classify_error(msg: str) -> tuple[ErrorCode, str]:
        m = msg.lower()
        for code, (desc, pred) in ERROR_RULES.items():
            if pred(m):
                return (code, desc)
        return (ErrorCode.OTHER, msg)

    used_codes: dict[str, str] = {}

    with Live(console=console, refresh_per_second=4) as live:
        for fut in asyncio.as_completed(tasks):
            kind, mid, res = await fut
            acc[mid][kind].append(CallResult(content=res.content, exc=res.exc, latency_s=res.latency_s))

            # When we have REPEATS for both kinds, build ModelProbe
            if len(acc[mid]["responses"]) >= REPEATS and len(acc[mid]["chat"]) >= REPEATS:
                completed_models += 1
                probe = ModelProbe(
                    model_id=mid,
                    responses=ProbeRun(model_id=mid, calls=acc[mid]["responses"]),
                    chat=ProbeRun(model_id=mid, calls=acc[mid]["chat"]),
                )
                if probe.any_ok:
                    oks.append(probe)
                else:
                    fails.append(probe)

            in_flight = total_models - completed_models
            new_table = make_results_table(
                title=f"OK models — in-flight remaining: {in_flight}",
                header_style="bold magenta",
                model_ratio=6,
            )

            def fmt_latency(obj) -> str:
                v = _avg_lat(obj)
                return f" {v:.1f}s" if v is not None else ""

            def render_row(r: ModelProbe, end_section: bool):
                # Always render separate columns; collapse duplication only when both-ok
                resp_cell = ""
                chat_cell = ""
                if r.responses.ok and r.chat.ok:
                    resp_cell = ok_cell(r.responses)
                    chat_cell = ok_cell(r.chat)
                else:
                    resp_cell = ok_cell(r.responses) if r.responses.ok else err_cell(r.responses)
                    chat_cell = ok_cell(r.chat) if r.chat.ok else err_cell(r.chat)
                new_table.add_row(
                    r.model_id,
                    resp_cell or "",
                    chat_cell or "",
                    end_section=end_section,
                )

            oks_both = [r for r in oks if r.responses.ok and r.chat.ok]
            oks_resp_only = [r for r in oks if r.responses.ok and not r.chat.ok]
            oks_chat_only = [r for r in oks if r.chat.ok and not r.responses.ok]
            oks_both.sort(
                key=lambda r: (
                    priority_index(r.model_id),
                    latency_both_key(r),
                    r.model_id,
                )
            )
            oks_resp_only.sort(
                key=lambda r: (
                    priority_index(r.model_id),
                    latency_resp_key(r),
                    r.model_id,
                )
            )
            oks_chat_only.sort(
                key=lambda r: (
                    priority_index(r.model_id),
                    latency_chat_key(r),
                    r.model_id,
                )
            )

            # Render both-ok rows into the single-column OK table
            for r, end_section in iter_with_break(oks_both, lambda x: classify(x.model_id)):
                render_row(r, end_section)

            # Prepare separate tables for responses-ok-only and chat-ok-only
            resp_table = make_results_table(
                title="Responses OK only",
                header_style="bold magenta",
                model_ratio=3,
            )

            chat_table = make_results_table(
                title="Chat OK only",
                header_style="bold magenta",
                model_ratio=3,
            )

            # Populate responses-ok-only
            for r, end_section in iter_with_break(oks_resp_only, lambda x: classify(x.model_id)):
                resp_table.add_row(
                    r.model_id,
                    ok_cell(r.responses),
                    ok_cell(r.chat) if r.chat.ok else err_cell(r.chat),
                    end_section=end_section,
                )

            # Populate chat-ok-only
            for r, end_section in iter_with_break(oks_chat_only, lambda x: classify(x.model_id)):
                chat_table.add_row(
                    r.model_id,
                    ok_cell(r.responses) if r.responses.ok else err_cell(r.responses),
                    ok_cell(r.chat),
                    end_section=end_section,
                )

            # Show partial (half-arrived) rows with 'waiting…'
            partials_resp: list[tuple[str, str, str]] = []
            partials_chat: list[tuple[str, str, str]] = []
            for mid, pair in acc.items():
                rpart = pair["responses"]
                cpart = pair["chat"]
                if (len(rpart) > 0 and len(cpart) < REPEATS) or (len(cpart) > 0 and len(rpart) < REPEATS):
                    if len(rpart) > 0 and len(cpart) < REPEATS:
                        if kind_ok(mid, "responses"):
                            resp_cell = cell_for_kind(mid, "responses")
                            chat_cell = WAITING_CELL
                            partials_resp.append((mid, resp_cell, chat_cell))
                    elif len(cpart) > 0 and len(rpart) < REPEATS:
                        if kind_ok(mid, "chat"):
                            chat_cell = cell_for_kind(mid, "chat")
                            resp_cell = WAITING_CELL
                            partials_chat.append((mid, resp_cell, chat_cell))

            partials_resp.sort(key=partials_sort_key("responses"))
            partials_chat.sort(key=partials_sort_key("chat"))

            # Append in-flight rows to the pessimistic groups
            if partials_resp:
                for (mid, rc, cc), end_section in iter_with_break(partials_resp, lambda x: classify(x[0])):
                    resp_table.add_row(mid, rc, cc, end_section=end_section)
            if partials_chat:
                for (mid, rc, cc), end_section in iter_with_break(partials_chat, lambda x: classify(x[0])):
                    chat_table.add_row(mid, rc, cc, end_section=end_section)

            # Render OTHER family models at the very bottom
            others_all = sorted([mid for mid in filtered if family_of(mid) == Family.OTHER])
            others_table = make_results_table(
                title="Other models (unclassified)",
                header_style="bold magenta",
                model_ratio=3,
            )
            for mid in others_all:
                rc, cc = (cell_for_kind(mid, "responses"), cell_for_kind(mid, "chat"))
                others_table.add_row(mid, rc, cc)

            live.update(Group(new_table, resp_table, chat_table, others_table))

    console.print()  # blank line after live display
    if fails:
        fails.sort(key=lambda r: sort_priority(r.model_id))
        fail_table = Table(
            show_header=True,
            header_style="bold red",
            title="Failures",
            expand=True,
            box=box.SIMPLE,
        )
        fail_table.add_column("Model", overflow="ellipsis", no_wrap=True, ratio=3, header_style="bold")
        fail_table.add_column("Responses", overflow="ellipsis", no_wrap=True, ratio=2)
        fail_table.add_column("Chat", overflow="ellipsis", no_wrap=True, ratio=2)
        for i, r in enumerate(fails):
            rcell = err_cell(r.responses)
            ccell = err_cell(r.chat)
            nxt = classify(fails[i + 1].model_id) if i + 1 < len(fails) else None
            curr = classify(r.model_id)
            end_section = nxt is not None and nxt != curr
            fail_table.add_row(r.model_id, rcell, ccell, end_section=end_section)
        console.print(fail_table)
        console.print()  # blank line
    bad_count = len(fails)
    console.print(f"[green]Success (any ok):[/green] {len(oks)}  |  [red]Failed (both failed):[/red] {bad_count}")

    if used_codes:
        legend = Table(
            show_header=True,
            header_style="bold cyan",
            title="Legend (error codes)",
            expand=True,
            box=box.SIMPLE,
        )
        legend.add_column("Code")
        legend.add_column("Meaning", overflow="fold")
        for code, meaning in sorted(used_codes.items()):
            legend.add_row(code, meaning)
        console.print(legend)


if __name__ == "__main__":
    asyncio.run(main())
