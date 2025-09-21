"""Probe OpenAI models via Responses and Chat APIs.

Usage:
    adgn-openai-probe [--sample N] [--concurrency C] [--repeats R] [--max-qps Q] [--stream]

Behavior:
- Lists available models, filters out non-target families, optional sampling
- For each (model, API kind), runs up to R repeats BUT stops early on fatal errors
- Concurrency/QPS are enforced per-call via a global semaphore + limiter
- Streams either JSONL events or a live Rich table with grouped summaries

Cells show: success rate %, avg latency among successes, and top error code (+ when multiple kinds)
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
import json
import random
import re
import sys
import time
from typing import Any, Final, cast

from aiolimiter import AsyncLimiter
from openai import AsyncOpenAI
from openai._exceptions import APIStatusError
from openai.types.responses.function_tool_param import FunctionToolParam
from openai.types.responses.tool_choice_function_param import ToolChoiceFunctionParam
from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.table import Table

# Textual (Rich-based TUI framework)
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static
from textual.reactive import reactive
from textual.events import Key


# ---------- Constants & utilities ----------

INF: float = float("inf")


# ---------- Data classes ----------


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


# ---------- Prompt/tools used in probe ----------

_GET_TIME_NAME: Final[str] = "get_time"
PROMPT = "What's the time in Prague? Use get_time."
TOOL_FUNCTION = {
    "name": _GET_TIME_NAME,
    "description": "Get current time for a city",
    "parameters": {
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
        "additionalProperties": False,
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
        lambda m: "server had an error" in m
        or "an error occurred while processing" in m,
    ),
    ErrorCode.NOT_FOUND: (
        "Model does not exist or access denied",
        lambda m: "does not exist" in m
        or "do not have access" in m
        or "model not found" in m
        or "not available" in m,
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

# Fatal (non-repeatable) error codes — cancel remaining repeats on first occurrence
FATAL_CODES: set[ErrorCode] = {
    ErrorCode.TTS_MODEL,
    ErrorCode.INVALID_REQUEST,
    ErrorCode.INVALID_HEADERS,
    ErrorCode.AUDIO_REQUIRED,
    ErrorCode.FORBIDDEN,
    ErrorCode.TOOLS_UNSUPPORTED,
    ErrorCode.NOT_FOUND,
    ErrorCode.NOT_CHAT,
    ErrorCode.RESP_ONLY,
}


# ---------- Helpers shared across output modes ----------


def _squeeze_one_line(text: str, max_len: int = 120) -> str:
    s = " ".join(str(text).split())
    return s if len(s) <= max_len else s[: max_len - 1] + "…"


def msg_from_exc(e: BaseException | None) -> str:
    if e is None:
        return ""
    if isinstance(e, APIStatusError):
        body = e.body
        msg = (
            body.get("message")
            if isinstance(body, dict) and "message" in body
            else e.message
        )
        return msg or repr(e)
    return str(e) or repr(e)


def classify_error(msg: str) -> tuple[ErrorCode, str]:
    m = msg.lower()
    for code, (desc, pred) in ERROR_RULES.items():
        if pred(m):
            return (code, desc)
    return (ErrorCode.OTHER, msg)


# Central tool-call inspector used by snippet extractors


def _tool_ok_if_expected(name: str | None, args: object) -> bool:
    """Return True if tool call matches our expected probe signature.
    Accepts either dict args or JSON string; supports get_time.
    """
    if name != "get_time":
        return False
    args_obj = args
    if isinstance(args, str):
        # Let exceptions bubble up if malformed JSON - indicates misuse
        args_obj = json.loads(args)
    return isinstance(args_obj, dict) and args_obj == {"city": "Prague"}


# ---------- Snippet extractors ----------


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


# ---------- Probe spec creators ----------


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
            resp = await asyncio.wait_for(
                spec.create(client, model_id),
                timeout=REQUEST_TIMEOUT,
            )
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
FAMILY_RES = {
    fam: re.compile(pattern, re.IGNORECASE) for fam, pattern in FAMILY_RULES.items()
}
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

# Global family priority for ordering
FAMILY_PRIORITY: list[Family] = [
    Family.GPT_5,
    Family.O3,
    Family.O4_MINI,
    Family.O1,
    Family.GPT_41,
]


def family_of(mid: str) -> Family:
    for fam, rx in FAMILY_RES.items():
        if rx.search(mid):
            return fam
    return Family.OTHER


def is_excluded(mid: str) -> bool:
    return family_of(mid) in FAMILY_DROP


def priority_index(mid: str) -> int:
    fam = family_of(mid)
    try:
        return FAMILY_PRIORITY.index(fam)
    except ValueError:
        return len(FAMILY_PRIORITY)


# ---------- Cell stats and formatting --------------------------------------


@dataclass(frozen=True)
class CellStats:
    total: int
    ok: int
    success_rate_pct: int
    succ_avg_s: float | None
    succ_std_s: float | None
    first_snippet: str | None
    top_error_code: ErrorCode | None
    top_error_desc: str | None
    error_kinds: int


def compute_cell_stats(calls: list[CallResult]) -> CellStats:
    total = len(calls)
    ok_calls = [c for c in calls if c.ok]
    ok = len(ok_calls)
    success_rate_pct = int(round((ok / total) * 100)) if total else 0

    # Latency among successful
    succ_lats = [float(c.latency_s) for c in ok_calls if c.latency_s is not None]
    succ_avg_s = (sum(succ_lats) / len(succ_lats)) if succ_lats else None
    succ_std_s: float | None = None
    if succ_lats and len(succ_lats) >= 2 and succ_avg_s is not None:
        m = succ_avg_s
        var_val = sum((x - m) ** 2 for x in succ_lats) / len(succ_lats)
        succ_std_s = var_val**0.5

    # First success snippet if any
    first_snippet: str | None = None
    for c in ok_calls:
        if c.content:
            first_snippet = c.content
            break

    # Error summary among unsuccessful
    err_codes: list[ErrorCode] = []
    code_desc: dict[ErrorCode, str] = {}
    for c in calls:
        if not c.ok:
            msg = msg_from_exc(c.exc)
            code, desc = classify_error(msg)
            err_codes.append(code)
            code_desc.setdefault(code, desc)
    top_error_code: ErrorCode | None = None
    top_error_desc: str | None = None
    error_kinds = 0
    if err_codes:
        cnt = Counter(err_codes)
        top_error_code = cnt.most_common(1)[0][0]
        top_error_desc = code_desc.get(top_error_code)
        error_kinds = len(cnt)

    return CellStats(
        total=total,
        ok=ok,
        success_rate_pct=success_rate_pct,
        succ_avg_s=succ_avg_s,
        succ_std_s=succ_std_s,
        first_snippet=first_snippet,
        top_error_code=top_error_code,
        top_error_desc=top_error_desc,
        error_kinds=error_kinds,
    )


def build_cell(calls: list[CallResult]) -> tuple[str, ErrorCode | None, str | None]:
    """Build a single rich cell with success rate, success latency, and top error."""
    if not calls:
        return ("[yellow]waiting…[/yellow]", None, None)

    stats = compute_cell_stats(calls)

    # Build compact suffix: [<SR%>|<avg_s>|e=<CODE><+>]
    parts: list[str] = [f"{stats.success_rate_pct}%"]
    if stats.succ_avg_s is not None:
        parts.append(f"{stats.succ_avg_s:.1f}s")
    code_ret: ErrorCode | None = None
    desc_ret: str | None = None
    if stats.ok < stats.total and stats.top_error_code is not None:
        plus = "+" if stats.error_kinds > 1 else ""
        parts.append(f"e={stats.top_error_code.value}{plus}")
        code_ret = stats.top_error_code
        desc_ret = stats.top_error_desc
    suffix = f" [{'|'.join(parts)}]" if parts else ""

    # Success path: show ✓, optional snippet (hide literal 'tool OK'), and suffix
    if stats.ok > 0:
        base = (stats.first_snippet or "").removeprefix("✓ ").strip()
        if base == "tool OK":
            base = ""
        if base:
            return (f"[green]✓ {base}{suffix}[/green]", code_ret, desc_ret)
        return (f"[green]✓{suffix}[/green]", code_ret, desc_ret)

    # All failed: show top error code (+ if multiple kinds) and 0%
    code_txt = stats.top_error_code.value if stats.top_error_code else "ERROR"
    plus = "+" if stats.error_kinds > 1 else ""
    return (
        f"[red]{code_txt}{plus} [{stats.success_rate_pct}%][/red]",
        stats.top_error_code,
        stats.top_error_desc,
    )


# ---------- Output consumers (event-queue based) ----------------------------


Event = tuple[str, str, ProbeResult | None]  # (kind, model, result or None for done)


async def consume_stream_jsonl(
    out_q: asyncio.Queue[Event],
    total_runners: int,
    filtered: list[str],
) -> None:
    ok_calls = 0
    fail_calls = 0
    finished = 0

    def iso_ts() -> str:
        return datetime.now(UTC).isoformat()

    while finished < total_runners:
        kind, mid, res = await out_q.get()
        if res is None:
            finished += 1
            continue
        rec: dict[str, Any] = {
            "ts": iso_ts(),
            "model": mid,
            "family": family_of(mid).value,
            "kind": kind,
            "ok": res.ok,
            "latency_s": res.latency_s,
        }
        if res.ok:
            if res.content is not None:
                rec["snippet"] = res.content
            ok_calls += 1
        else:
            msg = msg_from_exc(res.exc)
            code, _ = classify_error(msg)
            rec["code"] = code.value
            rec["error"] = msg
            fail_calls += 1
        print(json.dumps(rec), flush=True)

    summary = {
        "ts": iso_ts(),
        "type": "summary",
        "ok_calls": ok_calls,
        "failed_calls": fail_calls,
        "total_calls": ok_calls + fail_calls,
        "models": len(filtered),
    }
    print(json.dumps(summary), flush=True)


async def consume_stream_rich(
    out_q: asyncio.Queue[Event],
    total_runners: int,
    filtered: list[str],
    repeats: int,
) -> None:
    oks: list[ModelProbe] = []
    fails: list[ModelProbe] = []
    total_models = len(filtered)
    completed_models = 0
    finished = 0

    acc: dict[str, dict[str, list[CallResult]]] = {
        mid: {"responses": [], "chat": []} for mid in filtered
    }
    done_flags: dict[str, dict[str, bool]] = {
        mid: {"responses": False, "chat": False} for mid in filtered
    }
    finalized: set[str] = set()  # mids we added to oks/fails

    console = Console()

    def _avg_lat(obj) -> float | None:
        if isinstance(obj, ProbeRun):
            return obj.avg_latency_s
        lat = getattr(obj, "latency_s", None)
        return float(lat) if isinstance(lat, (int, float)) else None

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

    used_codes: dict[str, str] = {}

    with Live(console=console, refresh_per_second=4) as live:
        while finished < total_runners:
            kind, mid, res = await out_q.get()
            if res is None:
                done_flags[mid][kind] = True
                if mid not in finalized and all(done_flags[mid].values()):
                    completed_models += 1
                    probe = ModelProbe(
                        model_id=mid,
                        responses=ProbeRun(model_id=mid, calls=acc[mid]["responses"]),
                        chat=ProbeRun(model_id=mid, calls=acc[mid]["chat"]),
                    )
                    (oks if probe.any_ok else fails).append(probe)
                    finalized.add(mid)
                finished += 1
            else:
                acc[mid][kind].append(
                    CallResult(
                        content=res.content, exc=res.exc, latency_s=res.latency_s
                    ),
                )
                if not res.ok:
                    msg = msg_from_exc(res.exc)
                    code, desc = classify_error(msg)
                    if code != ErrorCode.OTHER:
                        used_codes.setdefault(code.value, desc)

            in_flight = total_models - completed_models
            new_table = make_results_table(
                title=f"OK models — in-flight remaining: {in_flight}",
                header_style="bold magenta",
                model_ratio=6,
            )

            def render_row(table: Table, r: ModelProbe, end_section: bool):
                rcell, rcode, rdesc = build_cell(r.responses.calls)
                ccell, ccode, cdesc = build_cell(r.chat.calls)
                if rcode and rdesc:
                    used_codes.setdefault(
                        rcode.value if isinstance(rcode, ErrorCode) else str(rcode),
                        rdesc,
                    )
                if ccode and cdesc:
                    used_codes.setdefault(
                        ccode.value if isinstance(ccode, ErrorCode) else str(ccode),
                        cdesc,
                    )
                table.add_row(
                    r.model_id,
                    rcell or "",
                    ccell or "",
                    end_section=end_section,
                )

            # Render merged per-model rows when both kinds have any arrivals (success or error)
            both_arrived: list[ModelProbe] = []
            for mid2 in filtered:
                r_calls = acc[mid2]["responses"]
                c_calls = acc[mid2]["chat"]
                if r_calls and c_calls:
                    both_arrived.append(
                        ModelProbe(
                            model_id=mid2,
                            responses=ProbeRun(model_id=mid2, calls=r_calls),
                            chat=ProbeRun(model_id=mid2, calls=c_calls),
                        ),
                    )
            both_arrived.sort(
                key=lambda r: (
                    priority_index(r.model_id),
                    latency_both_key(r),
                    r.model_id,
                ),
            )
            for r, end_section in iter_with_break(
                both_arrived,
                lambda x: family_of(x.model_id).value,
            ):
                render_row(new_table, r, end_section)

            resp_table = make_results_table(
                title="Responses arrived; Chat waiting",
                header_style="bold magenta",
                model_ratio=3,
            )

            chat_table = make_results_table(
                title="Chat arrived; Responses waiting",
                header_style="bold magenta",
                model_ratio=3,
            )

            partials_resp: list[tuple[str, str, str]] = []
            partials_chat: list[tuple[str, str, str]] = []
            for mid3, pair in acc.items():
                rpart = pair["responses"]
                cpart = pair["chat"]
                # Exactly one side has arrivals → partials; avoid duplicating rows present in the merged table
                if len(rpart) > 0 and len(cpart) == 0:
                    rc, rcode, rdesc = build_cell(rpart)
                    if rcode and rdesc:
                        used_codes.setdefault(
                            rcode.value if isinstance(rcode, ErrorCode) else str(rcode),
                            rdesc,
                        )
                    partials_resp.append((mid3, rc, "[yellow]waiting…[/yellow]"))
                if len(cpart) > 0 and len(rpart) == 0:
                    cc, ccode, cdesc = build_cell(cpart)
                    if ccode and cdesc:
                        used_codes.setdefault(
                            ccode.value if isinstance(ccode, ErrorCode) else str(ccode),
                            cdesc,
                        )
                    partials_chat.append((mid3, "[yellow]waiting…[/yellow]", cc))

            partials_resp.sort(key=partials_sort_key("responses"))
            partials_chat.sort(key=partials_sort_key("chat"))

            if partials_resp:
                for (mid4, rc, cc), end_section in iter_with_break(
                    partials_resp,
                    lambda x: family_of(x[0]).value,
                ):
                    resp_table.add_row(mid4, rc, cc, end_section=end_section)
            if partials_chat:
                for (mid5, rc, cc), end_section in iter_with_break(
                    partials_chat,
                    lambda x: family_of(x[0]).value,
                ):
                    chat_table.add_row(mid5, rc, cc, end_section=end_section)

            others_all = sorted(
                [mid6 for mid6 in filtered if family_of(mid6) == Family.OTHER],
            )
            others_table = make_results_table(
                title="Other models (unclassified)",
                header_style="bold magenta",
                model_ratio=3,
            )
            for mid7 in others_all:
                rc, _, _ = build_cell(acc[mid7]["responses"])
                cc, _, _ = build_cell(acc[mid7]["chat"])
                others_table.add_row(mid7, rc, cc)

            live.update(Group(new_table, resp_table, chat_table, others_table))

    console.print()
    if fails:
        fails.sort(key=lambda r: (family_of(r.model_id).value, r.model_id))
        fail_table = Table(
            show_header=True,
            header_style="bold red",
            title="Failures",
            expand=True,
            box=box.SIMPLE,
        )
        fail_table.add_column(
            "Model",
            overflow="ellipsis",
            no_wrap=True,
            ratio=3,
            header_style="bold",
        )
        fail_table.add_column("Responses", overflow="ellipsis", no_wrap=True, ratio=2)
        fail_table.add_column("Chat", overflow="ellipsis", no_wrap=True, ratio=2)
        for i, r in enumerate(fails):
            rcell, rcode, rdesc = build_cell(r.responses.calls)
            ccell, ccode, cdesc = build_cell(r.chat.calls)
            if rcode and rdesc:
                used_codes.setdefault(
                    rcode.value if isinstance(rcode, ErrorCode) else str(rcode), rdesc
                )
            if ccode and cdesc:
                used_codes.setdefault(
                    ccode.value if isinstance(ccode, ErrorCode) else str(ccode), cdesc
                )
            nxt = family_of(fails[i + 1].model_id).value if i + 1 < len(fails) else None
            curr = family_of(r.model_id).value
            end_section = nxt is not None and nxt != curr
            fail_table.add_row(r.model_id, rcell, ccell, end_section=end_section)
        console.print(fail_table)
        console.print()
    bad_count = len(fails)
    console.print(
        f"[green]Success (any ok):[/green] {len(oks)}  |  [red]Failed (both failed):[/red] {bad_count}",
    )

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
        for code_str, meaning in sorted(used_codes.items()):
            legend.add_row(code_str, meaning)
        console.print(legend)


# ---------- Textual TUI (interactive, refreshing) --------------------------


class ProbeTUI(App):
    """Interactive TUI for the OpenAI probe.

    Keys:
      - f: toggle showing models that had a fatal error
      - q: quit
    """

    CSS = """
    Screen { align: center middle; }
    #body { width: 100%; height: auto; }
    """

    BINDINGS = [
        ("f", "toggle_fatal", "Toggle fatal models"),
        ("tab", "next_family", "Next family"),
        ("q", "quit", "Quit"),
    ]

    show_fatal: bool = reactive(False)
    family_idx: int = reactive(0)

    def __init__(
        self,
        *,
        out_q: asyncio.Queue[Event],
        total_runners: int,
        filtered: list[str],
        repeats: int,
        initial_show_fatal: bool = False,
    ) -> None:
        super().__init__()
        self.out_q = out_q
        self.total_runners = total_runners
        self.filtered = filtered
        self.repeats = repeats
        self.show_fatal = initial_show_fatal
        # Compute family choices present in this run (+ ALL)
        present = set(family_of(mid) for mid in filtered)
        ordered: list[Family] = [fam for fam in FAMILY_PRIORITY if fam in present]
        if Family.OTHER in present and Family.OTHER not in ordered:
            ordered.append(Family.OTHER)
        self.family_choices: list[Family | None] = [None, *ordered]  # None = ALL
        self.family_idx = 0
        # Accumulators/state (mirrors consume_stream_rich)
        self.acc: dict[str, dict[str, list[CallResult]]] = {
            mid: {"responses": [], "chat": []} for mid in filtered
        }
        self.done_flags: dict[str, dict[str, bool]] = {
            mid: {"responses": False, "chat": False} for mid in filtered
        }
        self.finalized: set[str] = set()
        self.completed_models = 0
        self.finished = 0
        self.used_codes: dict[str, str] = {}
        self.fatal_by_mid: dict[str, bool] = {mid: False for mid in filtered}
        self.oks: list[ModelProbe] = []
        self.fails: list[ModelProbe] = []

    def compose(self) -> ComposeResult:  # type: ignore[override]
        yield Header(show_clock=True)
        self.body = Static(id="body")
        yield self.body
        yield Footer()

    async def on_mount(self) -> None:
        # Start background reader that consumes events and updates the view
        self._reader_task = asyncio.create_task(self._reader_loop())
        # Initial render
        self._render_view()

    async def _reader_loop(self) -> None:
        while self.finished < self.total_runners:
            kind, mid, res = await self.out_q.get()
            if res is None:
                self.done_flags[mid][kind] = True
                if mid not in self.finalized and all(self.done_flags[mid].values()):
                    self.completed_models += 1
                    probe = ModelProbe(
                        model_id=mid,
                        responses=ProbeRun(
                            model_id=mid, calls=self.acc[mid]["responses"]
                        ),
                        chat=ProbeRun(model_id=mid, calls=self.acc[mid]["chat"]),
                    )
                    (self.oks if probe.any_ok else self.fails).append(probe)
                    self.finalized.add(mid)
                self.finished += 1
            else:
                self.acc[mid][kind].append(
                    CallResult(
                        content=res.content, exc=res.exc, latency_s=res.latency_s
                    ),
                )
                if not res.ok:
                    msg = msg_from_exc(res.exc)
                    code, desc = classify_error(msg)
                    if code != ErrorCode.OTHER:
                        self.used_codes.setdefault(code.value, desc)
                    if code in FATAL_CODES:
                        self.fatal_by_mid[mid] = True
            self._render_view()
        # Final render to include failure summary and legend
        self._render_view(final=True)

    def action_toggle_fatal(self) -> None:
        self.show_fatal = not self.show_fatal
        self._render_view()

    def action_quit(self) -> None:
        self.exit()

    def action_next_family(self) -> None:
        # Cycle to next family (including ALL)
        self.family_idx = (self.family_idx + 1) % len(self.family_choices)
        self._render_view()

    def on_key(self, event: Key) -> None:  # intercept Tab from default focus switching
        if event.key == "tab":
            self.action_next_family()
            event.stop()

    @property
    def current_family(self) -> Family | None:
        try:
            return self.family_choices[self.family_idx]
        except Exception:
            return None

    def _filter_mid(self, mid: str) -> bool:
        fam_ok = (self.current_family is None) or (
            family_of(mid) == self.current_family
        )
        fatal_ok = self.show_fatal or not self.fatal_by_mid.get(mid, False)
        return fam_ok and fatal_ok

    def _avg_lat(self, obj) -> float | None:
        if isinstance(obj, ProbeRun):
            return obj.avg_latency_s
        lat = getattr(obj, "latency_s", None)
        return float(lat) if isinstance(lat, (int, float)) else None

    def _make_results_table(
        self,
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

    def _iter_with_break(self, rows, key_fn):
        if not rows:
            return []
        result = []
        for idx, row in enumerate(rows):
            curr = key_fn(row)
            nxt = key_fn(rows[idx + 1]) if idx + 1 < len(rows) else None
            result.append((row, nxt is not None and nxt != curr))
        return result

    def _partials_sort_key(self, kind: str):
        def key(item: tuple[str, str, str]):
            mid = item[0]
            avg = (
                self._avg_lat(ProbeRun(model_id=mid, calls=self.acc[mid][kind])) or INF
            )
            return (priority_index(mid), avg, mid)

        return key

    def _latency_both_key(self, r: ModelProbe) -> float:
        vals = [
            v
            for v in (self._avg_lat(r.responses), self._avg_lat(r.chat))
            if v is not None
        ]
        return min(vals) if vals else INF

    def _render_view(self, final: bool = False) -> None:
        # Build tables similar to consume_stream_rich, but apply fatal filter
        # Visible set counts (respect current family + fatal filter)
        visible_mids = [mid for mid in self.filtered if self._filter_mid(mid)]
        total_models = len(visible_mids)
        completed_visible = sum(
            1 for mid in visible_mids if all(self.done_flags[mid].values())
        )
        in_flight = total_models - completed_visible

        fam_label = (
            self.current_family.value
            if isinstance(self.current_family, Family)
            else "ALL"
        )
        new_table = self._make_results_table(
            title=f"OK models — in-flight remaining: {in_flight}  |  family: {fam_label}  |  fatal: {'ON' if self.show_fatal else 'OFF'} (f/toggle fatal, tab/next family)",
            header_style="bold magenta",
            model_ratio=6,
        )

        def render_row(table: Table, r: ModelProbe, end_section: bool):
            rcell, rcode, rdesc = build_cell(r.responses.calls)
            ccell, ccode, cdesc = build_cell(r.chat.calls)
            if rcode and rdesc:
                self.used_codes.setdefault(
                    rcode.value if isinstance(rcode, ErrorCode) else str(rcode), rdesc
                )
            if ccode and cdesc:
                self.used_codes.setdefault(
                    ccode.value if isinstance(ccode, ErrorCode) else str(ccode), cdesc
                )
            if self._filter_mid(r.model_id):
                table.add_row(
                    r.model_id, rcell or "", ccell or "", end_section=end_section
                )

        # Merged rows where both sides have arrivals
        both_arrived: list[ModelProbe] = []
        for mid in self.filtered:
            if not self._filter_mid(mid):
                continue
            r_calls = self.acc[mid]["responses"]
            c_calls = self.acc[mid]["chat"]
            if r_calls and c_calls:
                both_arrived.append(
                    ModelProbe(
                        model_id=mid,
                        responses=ProbeRun(model_id=mid, calls=r_calls),
                        chat=ProbeRun(model_id=mid, calls=c_calls),
                    ),
                )
        both_arrived.sort(
            key=lambda r: (
                priority_index(r.model_id),
                self._latency_both_key(r),
                r.model_id,
            ),
        )
        for r, end_section in self._iter_with_break(
            both_arrived, lambda x: family_of(x.model_id).value
        ):
            render_row(new_table, r, end_section)

        # Partials
        resp_table = self._make_results_table(
            title="Responses arrived; Chat waiting",
            header_style="bold magenta",
            model_ratio=3,
        )
        chat_table = self._make_results_table(
            title="Chat arrived; Responses waiting",
            header_style="bold magenta",
            model_ratio=3,
        )
        partials_resp: list[tuple[str, str, str]] = []
        partials_chat: list[tuple[str, str, str]] = []
        for mid, pair in self.acc.items():
            if not self._filter_mid(mid):
                continue
            rpart = pair["responses"]
            cpart = pair["chat"]
            if len(rpart) > 0 and len(cpart) == 0:
                rc, rcode, rdesc = build_cell(rpart)
                if rcode and rdesc:
                    self.used_codes.setdefault(
                        rcode.value if isinstance(rcode, ErrorCode) else str(rcode),
                        rdesc,
                    )
                partials_resp.append((mid, rc, "[yellow]waiting…[/yellow]"))
            if len(cpart) > 0 and len(rpart) == 0:
                cc, ccode, cdesc = build_cell(cpart)
                if ccode and cdesc:
                    self.used_codes.setdefault(
                        ccode.value if isinstance(ccode, ErrorCode) else str(ccode),
                        cdesc,
                    )
                partials_chat.append((mid, "[yellow]waiting…[/yellow]", cc))
        partials_resp.sort(key=self._partials_sort_key("responses"))
        partials_chat.sort(key=self._partials_sort_key("chat"))
        for (mid4, rc, cc), end_section in self._iter_with_break(
            partials_resp, lambda x: family_of(x[0]).value
        ):
            resp_table.add_row(mid4, rc, cc, end_section=end_section)
        for (mid5, rc, cc), end_section in self._iter_with_break(
            partials_chat, lambda x: family_of(x[0]).value
        ):
            chat_table.add_row(mid5, rc, cc, end_section=end_section)

        # Others
        # Others table only when viewing ALL or specifically OTHER
        renderables = [new_table, resp_table, chat_table]
        if self.current_family is None or self.current_family == Family.OTHER:
            others_all = sorted(
                [
                    mid6
                    for mid6 in self.filtered
                    if family_of(mid6) == Family.OTHER and self._filter_mid(mid6)
                ]
            )
            others_table = self._make_results_table(
                title="Other models (unclassified)",
                header_style="bold magenta",
                model_ratio=3,
            )
            for mid7 in others_all:
                rc, _, _ = build_cell(self.acc[mid7]["responses"])
                cc, _, _ = build_cell(self.acc[mid7]["chat"])
                others_table.add_row(mid7, rc, cc)
            renderables.append(others_table)

        # Failures and legend at bottom (on final or when some failures already finalized)
        if final or self.fails:
            if self.fails:
                self.fails.sort(key=lambda r: (family_of(r.model_id).value, r.model_id))
                fail_table = Table(
                    show_header=True,
                    header_style="bold red",
                    title="Failures",
                    expand=True,
                    box=box.SIMPLE,
                )
                fail_table.add_column(
                    "Model",
                    overflow="ellipsis",
                    no_wrap=True,
                    ratio=3,
                    header_style="bold",
                )
                fail_table.add_column(
                    "Responses", overflow="ellipsis", no_wrap=True, ratio=2
                )
                fail_table.add_column(
                    "Chat", overflow="ellipsis", no_wrap=True, ratio=2
                )
                for i, r in enumerate(self.fails):
                    if not self._filter_mid(r.model_id):
                        continue
                    rcell, rcode, rdesc = build_cell(r.responses.calls)
                    ccell, ccode, cdesc = build_cell(r.chat.calls)
                    if rcode and rdesc:
                        self.used_codes.setdefault(
                            rcode.value if isinstance(rcode, ErrorCode) else str(rcode),
                            rdesc,
                        )
                    if ccode and cdesc:
                        self.used_codes.setdefault(
                            ccode.value if isinstance(ccode, ErrorCode) else str(ccode),
                            cdesc,
                        )
                    nxt = (
                        family_of(self.fails[i + 1].model_id).value
                        if i + 1 < len(self.fails)
                        else None
                    )
                    curr = family_of(r.model_id).value
                    end_section = nxt is not None and nxt != curr
                    fail_table.add_row(
                        r.model_id, rcell, ccell, end_section=end_section
                    )
                renderables.append(fail_table)
            if self.used_codes:
                legend = Table(
                    show_header=True,
                    header_style="bold cyan",
                    title="Legend (error codes)",
                    expand=True,
                    box=box.SIMPLE,
                )
                legend.add_column("Code")
                legend.add_column("Meaning", overflow="fold")
                for code_str, meaning in sorted(self.used_codes.items()):
                    legend.add_row(code_str, meaning)
                renderables.append(legend)

        # Update the body with grouped renderables
        self.body.update(Group(*renderables))


async def consume_stream_textual(
    out_q: asyncio.Queue[Event],
    total_runners: int,
    filtered: list[str],
    repeats: int,
    *,
    show_fatal: bool = False,
) -> None:
    app = ProbeTUI(
        out_q=out_q,
        total_runners=total_runners,
        filtered=filtered,
        repeats=repeats,
        initial_show_fatal=show_fatal,
    )
    await app.run_async()


# ---------- Runner orchestration -------------------------------------------


async def run_probe_series(
    *,
    kind: str,
    model_id: str,
    spec: ProbeSpec,
    repeats: int | None,
    sem: asyncio.Semaphore,
    limiter: AsyncLimiter,
    client: AsyncOpenAI,
    out_q: asyncio.Queue[Event],
) -> None:
    count = 0
    while repeats is None or count < repeats:
        async with sem:
            res = await _probe_once(
                client, model_id=model_id, spec=spec, limiter=limiter
            )
        await out_q.put((kind, model_id, res))
        count += 1
        if not res.ok:
            code, _ = classify_error(msg_from_exc(res.exc))
            if code in FATAL_CODES:
                break
    # Signal completion for this (kind, model)
    await out_q.put((kind, model_id, None))


# ---------- Main ------------------------------------------------------------


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Filter and test OpenAI models")
    parser.add_argument(
        "--sample", type=int, default=0, help="Randomly sample N models (0 = use all)"
    )
    parser.add_argument(
        "--concurrency", "-c", type=int, default=128, help="Max concurrent requests"
    )
    parser.add_argument(
        "--repeats",
        "-r",
        type=int,
        default=5,
        help="Repeats per probe per model (default: 5)",
    )
    parser.add_argument(
        "--max-qps", "-q", type=float, default=0.3, help="Global max QPS"
    )
    parser.add_argument(
        "--family",
        type=str,
        choices=[f.value for f in Family],
        help="Only run models in this family (e.g., gpt-5)",
    )
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Loop repeats forever until interrupted (fatal errors still stop that model/kind)",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Print events as a raw stream as they arrive (no table)",
    )
    parser.add_argument(
        "--show-fatal",
        action="store_true",
        help="Start with models that had a fatal error visible (toggle with 'f')",
    )
    return parser.parse_args(argv)


async def _async_main() -> None:
    args = parse_args()
    # Global limiter; support fractional QPS via the time window
    qps = float(args.max_qps)
    if qps <= 0:
        qps = 1.0
    limiter = AsyncLimiter(int(qps), 1.0) if qps >= 1.0 else AsyncLimiter(1, 1.0 / qps)

    async_client = AsyncOpenAI()
    print("Fetching model list …", file=sys.stderr)
    resp = await async_client.models.list()
    model_ids = [m.id for m in resp.data]
    print(f"Total models from API: {len(model_ids)}", file=sys.stderr)

    # Filtering
    filtered = [mid for mid in model_ids if not is_excluded(mid)]
    if args.family:
        filtered = [mid for mid in filtered if family_of(mid).value == args.family]
    print(f"After filtering rules: {len(filtered)}", file=sys.stderr)

    # Optional sampling
    if args.sample and args.sample < len(filtered):
        filtered = random.sample(filtered, args.sample)
        print(f"Sub-sampled to {len(filtered)} models (random)", file=sys.stderr)

    # Probe specs
    responses_spec = ProbeSpec(
        name="responses", create=_create_responses, snippet=_snippet_from_responses
    )
    chat_spec = ProbeSpec(name="chat", create=_create_chat, snippet=_snippet_from_chat)

    sem = asyncio.Semaphore(max(args.concurrency, 1))

    # Prioritized order using family heuristic
    prioritized = sorted(filtered, key=lambda mid: (priority_index(mid), mid))

    # Launch one runner per (kind, model); each runner sequences repeats and stops on fatal
    out_q: asyncio.Queue[Event] = asyncio.Queue()
    runners: list[asyncio.Task] = []
    repeats_effective: int | None = (
        None if args.continuous else max(int(args.repeats), 1)
    )
    for mid in prioritized:
        runners.append(
            asyncio.create_task(
                run_probe_series(
                    kind="responses",
                    model_id=mid,
                    spec=responses_spec,
                    repeats=repeats_effective,
                    sem=sem,
                    limiter=limiter,
                    client=async_client,
                    out_q=out_q,
                )
            )
        )
        runners.append(
            asyncio.create_task(
                run_probe_series(
                    kind="chat",
                    model_id=mid,
                    spec=chat_spec,
                    repeats=repeats_effective,
                    sem=sem,
                    limiter=limiter,
                    client=async_client,
                    out_q=out_q,
                )
            )
        )

    total_runners = len(runners)

    if args.stream:
        await consume_stream_jsonl(out_q, total_runners, filtered)
    else:
        # repeats value is not used for logic; pass a nonzero int for display
        disp_repeats = max(int(args.repeats), 1)
        await consume_stream_textual(
            out_q,
            total_runners,
            filtered,
            repeats=disp_repeats,
            show_fatal=bool(getattr(args, "show_fatal", False)),
        )

    await asyncio.gather(*runners, return_exceptions=True)


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
