"""Probe OpenAI models via Responses and Chat APIs.

- Filters model list by family and a configurable regex to exclude noise (e.g., fine‑tunes).
- Smart selection prioritizes models recently OK (from cache) and slowly samples others; skips very recently seen.
- Uses fast/slow QPS and repeats; early‑stops on fatal, non‑retryable errors.
- Emits JSONL events and persists faithful responses to XDG cache; TUI renders a live table.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from functools import partial
import json
import random
import os
import re
import sys
import time
from typing import Any, Final, Literal, cast
from types import MappingProxyType
from pathlib import Path

from aiolimiter import AsyncLimiter
from adgn.openai_utils.client_factory import _get_async_openai
from openai import AsyncOpenAI
from openai._exceptions import APIStatusError
from openai.types.responses.function_tool_param import FunctionToolParam
from openai.types.responses.tool_choice_function_param import ToolChoiceFunctionParam
from openai.types.responses import Response as ResponsesType
from openai.types.chat.chat_completion import ChatCompletion
from rich import box
from rich.console import Group
from rich.table import Table
from platformdirs import user_cache_dir
from pydantic import BaseModel, ConfigDict
from aiohttp import web
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static
from textual.reactive import reactive
from textual.events import Key
import asyncpg


# ---------- Constants & utilities ----------

INF: float = float("inf")

# Compiled at startup from --drop-regex (see _async_main). If None, no drops by regex.
DROP_MODEL_ID_RE: re.Pattern[str] | None = None

# Smart policy constants (hardcoded)
OK_LOOKBACK = timedelta(hours=24)
MIN_INTERVAL = timedelta(minutes=10)
FAIL_REPEATS = 1

# Health server settings
HEALTH_PORT = int(os.getenv("PROBE_HEALTH_PORT", "8080"))
HEALTH_PATH = "/health"
METRICS_PATH = "/metrics"

# Database settings
DB_HOST = os.getenv("DB_HOST", "timescaledb.observability.svc.cluster.local")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "openai_probe")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD")
if not DB_PASSWORD:
    raise ValueError("DB_PASSWORD environment variable is required but not set")
# Cache paths (XDG cache via platformdirs)
_CACHE_DIR = Path(user_cache_dir(appname="adgn-llm", appauthor=False)) / "openai_probe"

_CACHE_FILE = _CACHE_DIR / "history.jsonl"


def _ensure_cache_dir() -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _iso_ts() -> str:
    return datetime.now(UTC).isoformat()


def _log_event(event_type: str, **fields: Any) -> None:
    try:
        payload = {"ts": datetime.now(UTC).timestamp(), "type": event_type, **fields}
        print(json.dumps(payload, separators=(",", ":")), flush=True)
    except Exception:
        # Never let logging crash the probe
        pass


def _model_dump_like(obj: Any, *, exclude_none: bool = True) -> dict[str, Any] | None:
    """Return a JSON-serializable dict from SDK/Pydantic or plain dict objects.

    - If `obj` provides `model_dump`, call it with the given `exclude_none` flag.
    - If `obj` is already a dict, return it as-is.
    - Otherwise, return None.
    """
    if isinstance(obj, BaseModel):
        try:
            return cast(dict[str, Any], obj.model_dump(exclude_none=exclude_none))
        except Exception:
            return None
    if isinstance(obj, dict):
        return obj
    return None


class ErrorInfo(BaseModel):
    type: str | None = None
    message: str | None = None
    status_code: int | None = None
    body: Any | None = None
    request_id: str | None = None
    code: str | None = None


class CachedProbeError(RuntimeError):
    """Minimal error type used when hydrating cached probe results."""

    def __init__(self, info: ErrorInfo) -> None:
        message = info.message or ""
        super().__init__(message)
        self.message = message
        self.status_code = info.status_code
        self.body = info.body
        self.request_id = info.request_id
        self.code = info.code


class ProbeRecord(BaseModel):
    ts: datetime
    start_ts: datetime | None = None
    end_ts: datetime | None = None
    model: str
    kind: ProbeKind  # "responses" | "chat"
    ok: bool
    latency_s: float | None = None
    response: dict[str, Any] | None = None
    error: ErrorInfo | None = None


def _persist_result(res: "ProbeResult") -> None:
    """Append a single probe result to the JSONL cache."""
    _ensure_cache_dir()
    record = res.to_cache_record()
    with _CACHE_FILE.open("a", encoding="utf-8") as fh:
        fh.write(record.model_dump_json() + "\n")


# Database connection and initialization
_db_pool: asyncpg.Pool | None = None


async def _get_db_pool() -> asyncpg.Pool:
    """Get or create database connection pool."""
    global _db_pool
    if _db_pool is None:
        _db_pool = await asyncpg.create_pool(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            min_size=1,
            max_size=10,
        )
    return _db_pool


async def _init_database() -> None:
    """Ensure database connectivity; schema managed externally (k8s migration)."""
    await _get_db_pool()


async def _write_probe_result(res: "ProbeResult") -> None:
    """Write probe result to TimescaleDB."""
    if not res.start_ts or not res.end_ts:
        return  # Skip if missing timing data

    pool = await _get_db_pool()

    # Extract response data based on API type
    chat_json: Any | None = None
    responses_json: Any | None = None

    if res.ok and res.raw:
        if res.kind == "chat":
            chat_obj = res.raw_chat()
            if chat_obj is not None:
                chat_json = chat_obj.model_dump(exclude_none=False)
        elif res.kind == "responses":
            resp_obj = res.raw_responses()
            if resp_obj is not None:
                responses_json = resp_obj.model_dump(exclude_none=False)
            # Note: responses API may not have token counts in the same format

    # Extract error information
    error_code = None
    error_status = None
    error_body_json: Any | None = None
    if not res.ok and res.exc:
        # Strict: prefer OpenAI APIStatusError details when available
        if isinstance(res.exc, APIStatusError):
            error_status = res.exc.status_code
            resp = res.exc.response
            if resp is not None:
                try:
                    parsed = resp.json()
                    if isinstance(parsed, dict):
                        error_body_json = parsed
                except Exception:
                    pass
            if error_body_json is None:
                body = res.exc.body
                if isinstance(body, dict):
                    error_body_json = body
        # Classify error
        classification = res.error_classification
        if classification:
            error_code = classification[0].value

    # Get API key suffix
    api_key_suffix = None
    # Could extract from client if needed - for now skip

    # Get request ID
    request_id = None
    exc = res.exc
    if isinstance(exc, APIStatusError):
        request_id = exc.request_id
    elif res.ok:
        # Prefer the JSON payload if available
        if isinstance(chat_json, dict) and chat_json.get("id"):
            request_id = str(chat_json.get("id"))
        elif isinstance(responses_json, dict) and responses_json.get("id"):
            request_id = str(responses_json.get("id"))

    insert_sql = """
    INSERT INTO probe_results (
        start_time, end_time, latency_s, model, family, kind, success,
        error_code, error_status, error_body,
        chat_response,
        responses_body,
        request_id, api_key_suffix
    ) VALUES (
        $1, $2, $3, $4, $5, $6, $7,
        $8, $9, $10::jsonb,
        $11::jsonb,
        $12::jsonb, $13, $14
    )
    """

    async with pool.acquire() as conn:
        # JSON encode dicts for jsonb columns
        eb = json.dumps(error_body_json) if error_body_json is not None else None
        cj = json.dumps(chat_json) if chat_json is not None else None
        rj = json.dumps(responses_json) if responses_json is not None else None

        try:
            await conn.execute(
                insert_sql,
                res.start_ts,  # start_time
                res.end_ts,  # end_time
                res.latency_s,  # latency_s
                res.model_id,  # model
                family_of(res.model_id).value,  # family
                res.kind,  # kind
                res.ok,  # success
                error_code,  # error_code
                error_status,  # error_status
                eb,  # error_body (as JSON string, cast to jsonb)
                cj,  # chat_response (as JSON string, cast to jsonb)
                rj,  # responses_body (as JSON string, cast to jsonb)
                request_id,  # request_id
                api_key_suffix,  # api_key_suffix
            )
            _log_event(
                "db_write",
                model=res.model_id,
                kind=res.kind,
                ok=res.ok,
                has_error_body=bool(error_body_json),
            )
        except Exception as e:
            _log_event(
                "db_write_error",
                model=res.model_id,
                kind=res.kind,
                error=str(e),
            )
            raise


class _StreamRecordBase(BaseModel):
    ts: float
    type: str = "event"
    source: str = "adgn-openai-probe"
    model: str
    family: str
    kind: str
    tags: dict[str, str] | None = None


class StreamRecordOK(_StreamRecordBase):
    ok: Literal[True]
    latency_s: float | None = None
    response: dict[str, Any] | None = None
    response_str: str | None = None  # JSON string representation for LogQL


class StreamRecordError(_StreamRecordBase):
    ok: Literal[False]
    error: ErrorInfo
    error_str: str | None = None  # Error string for LogQL (code: message)


class KindStatusEntry(BaseModel):
    kind: str
    recent_ok: bool


class ModelSummary(BaseModel):
    model: str
    family: str
    recent_ok: bool
    recent_ok_by_kind: tuple[KindStatusEntry, ...]

    model_config = ConfigDict(frozen=True)


class ModelListRecord(BaseModel):
    ts: float
    type: Literal["models"] = "models"
    source: str = "adgn-openai-probe"
    model: str
    family: str
    recent_ok: bool
    recent_ok_by_kind: list[KindStatusEntry] | None = None
    tags: dict[str, str] | None = None


# ---------- Data classes ----------


@dataclass(frozen=True)
class ProbeResult:
    model_id: str
    kind: ProbeKind
    ok: bool
    exc: BaseException | None = None
    raw: Any | None = (
        None  # ChatCompletion when kind=="chat"; ResponsesType when kind=="responses"
    )
    start_ts: datetime | None = None
    end_ts: datetime | None = None
    latency_override_s: float | None = None

    @classmethod
    def success(
        cls,
        *,
        model_id: str,
        kind: ProbeKind,
        raw: ResponsesType | ChatCompletion,
        start_ts: datetime,
        end_ts: datetime,
    ) -> "ProbeResult":
        return cls(
            model_id=model_id,
            kind=kind,
            ok=True,
            raw=raw,
            start_ts=start_ts,
            end_ts=end_ts,
        )

    @classmethod
    def failure(
        cls,
        *,
        model_id: str,
        kind: ProbeKind,
        exc: BaseException,
        start_ts: datetime | None,
        end_ts: datetime,
    ) -> "ProbeResult":
        return cls(
            model_id=model_id,
            kind=kind,
            ok=False,
            exc=exc,
            start_ts=start_ts,
            end_ts=end_ts,
        )

    @property
    def latency_s(self) -> float | None:
        if not isinstance(self.start_ts, datetime) or not isinstance(
            self.end_ts, datetime
        ):
            return self.latency_override_s
        return float((self.end_ts - self.start_ts).total_seconds())

    @property
    def content(self) -> str | None:
        """Derive a short snippet from the raw response or error payload."""
        try:
            if self.ok and self.raw is not None:
                if self.kind == "responses":
                    resp = self.raw_responses()
                    if resp is not None:
                        return _snippet_from_responses(resp)
                if self.kind == "chat":
                    ch = self.raw_chat()
                    if ch is not None:
                        return _snippet_from_chat(ch)
            if not self.ok and self.exc is not None:
                return _squeeze_one_line(msg_from_exc(self.exc)) or None
        except Exception:
            # Do not let snippet extraction break probing
            return None
        return None

    @property
    def error_message(self) -> str:
        return msg_from_exc(self.exc)

    @property
    def error_classification(self) -> tuple[ErrorCode, str] | None:
        if self.ok or self.exc is None:
            return None
        return classify_error(self.error_message)

    def to_cache_record(self, *, ts: datetime | None = None) -> ProbeRecord:
        payload: dict[str, Any] | Any | None = None
        if self.ok and self.raw is not None:
            payload = _model_dump_like(self.raw, exclude_none=False) or self.raw
        err_info: ErrorInfo | None = None
        if not self.ok:
            classification = self.error_classification
            err_info = ErrorInfo(
                type=(type(self.exc).__name__ if self.exc is not None else None),
                message=self.error_message,
                status_code=(
                    getattr(self.exc, "status_code", None)
                    if self.exc is not None
                    else None
                ),
                body=(
                    getattr(self.exc, "body", None) if self.exc is not None else None
                ),
                request_id=(
                    getattr(self.exc, "request_id", None)
                    if self.exc is not None
                    else None
                ),
                code=(classification[0].value if classification else None),
            )
        return ProbeRecord(
            ts=ts or datetime.now(UTC),
            start_ts=self.start_ts,
            end_ts=self.end_ts,
            model=self.model_id,
            kind=self.kind,
            ok=self.ok,
            latency_s=self.latency_s,
            response=payload if self.ok else None,
            error=err_info,
        )

    @classmethod
    def from_record(cls, record: ProbeRecord) -> "ProbeResult":
        raw: Any | None = None
        if record.ok and record.response is not None:
            # Strict rehydration into SDK types; do not fall back to plain dicts
            if record.kind == "responses":
                if isinstance(record.response, dict):
                    raw = ResponsesType.model_validate(record.response)
                elif isinstance(record.response, ResponsesType):
                    raw = record.response
                else:
                    raise TypeError("Unexpected responses payload type in cache")
            elif record.kind == "chat":
                if isinstance(record.response, dict):
                    raw = ChatCompletion.model_validate(record.response)
                elif isinstance(record.response, ChatCompletion):
                    raw = record.response
                else:
                    raise TypeError("Unexpected chat payload type in cache")
            else:
                raise ValueError(f"Unknown kind in cache: {record.kind}")
        exc: BaseException | None = None
        if not record.ok:
            err = record.error
            if isinstance(err, ErrorInfo):
                info = err
            elif isinstance(err, dict):
                info = ErrorInfo.model_validate(err)
            else:
                info = ErrorInfo(message=str(err) if err is not None else None)
            exc = CachedProbeError(info)
        return cls(
            model_id=record.model,
            kind=record.kind,
            ok=record.ok,
            exc=exc,
            raw=raw,
            start_ts=record.start_ts,
            end_ts=record.end_ts,
            latency_override_s=record.latency_s,
        )

    # ---- Typed accessors to avoid casts in callers ----
    def raw_chat(self) -> ChatCompletion | None:
        if self.kind == "chat" and isinstance(self.raw, ChatCompletion):
            return self.raw
        return None

    def raw_responses(self) -> ResponsesType | None:
        if self.kind == "responses" and isinstance(self.raw, ResponsesType):
            return self.raw
        return None


@dataclass(frozen=True)
class ProbeRun:
    model_id: str
    calls: list[ProbeResult]

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


@dataclass(frozen=True)
class ModelProbe:
    model_id: str
    responses: ProbeRun
    chat: ProbeRun

    @property
    def any_ok(self) -> bool:
        return self.responses.ok or self.chat.ok


ProbeKind = Literal["responses", "chat"]


@dataclass(frozen=True)
class ProbeSpec:
    name: ProbeKind
    create: Callable[[AsyncOpenAI, str], Awaitable[Any]]


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


def _snippet_from_responses(resp: ResponsesType) -> str:
    # Accept typed Responses SDK object
    txt = resp.output_text
    if txt:
        return _squeeze_one_line(txt)
    # Fallback: inspect for output blocks and tool/function calls
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


def _snippet_from_chat(resp: ChatCompletion) -> str:
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
    # Fallback to attribute API if available
    choices = resp.choices
    content = choices[0].message.content if choices else None
    if content:
        return "✓ " + _squeeze_one_line(str(content))
    return "✓"


# ---------- Probe spec creators ----------


async def _create_responses(c: AsyncOpenAI, m: str, max_tokens: int):
    return await c.responses.create(
        model=m,
        input=PROMPT,
        tools=[GET_TIME_TOOL],
        tool_choice=GET_TIME_TOOL_CHOICE,
        max_output_tokens=max_tokens,
    )


async def _create_chat(c: AsyncOpenAI, m: str, max_tokens: int):
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
        max_completion_tokens=max_tokens,
    )


async def _probe_once(
    client: AsyncOpenAI,
    *,
    model_id: str,
    spec: ProbeSpec,
    limiter: AsyncLimiter,
) -> ProbeResult:
    start_ts: datetime | None = None
    try:
        async with limiter:
            start_ts = datetime.now(UTC)
            t0 = time.perf_counter()  # measure pure API latency, not queueing time
            resp = await asyncio.wait_for(
                spec.create(client, model_id),
                timeout=REQUEST_TIMEOUT,
            )
        _ = time.perf_counter() - t0
        return ProbeResult.success(
            model_id=model_id,
            kind=spec.name,
            raw=resp,
            start_ts=start_ts,
            end_ts=datetime.now(UTC),
        )
    except Exception as exc:
        # On failure, we still record timestamps around the attempted call
        return ProbeResult.failure(
            model_id=model_id,
            kind=spec.name,
            exc=exc,
            start_ts=start_ts,
            end_ts=datetime.now(UTC),
        )


# ---------- Filtering rules -------------------------------------------------


# Model family heuristic
class Family(str, Enum):
    # Kept/classifiable families only
    GPT_5 = "gpt-5"
    O3 = "o3"
    O4_MINI = "o4-mini"
    O1 = "o1"
    GPT_41 = "gpt-4.1"
    OTHER = "other"


FAMILY_RULES: dict[Family, str] = {
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
FAMILY_DROP: set[Family] = set()  # drop now handled by DROP_MODEL_ID_RE

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
    global DROP_MODEL_ID_RE
    return bool(DROP_MODEL_ID_RE.search(mid)) if DROP_MODEL_ID_RE is not None else False


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


def compute_cell_stats(calls: list[ProbeResult]) -> CellStats:
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
            classification = c.error_classification
            if classification:
                code, desc = classification
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


def build_cell(calls: list[ProbeResult]) -> tuple[str, ErrorCode | None, str | None]:
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


Event = tuple[
    ProbeKind, str, ProbeResult | None
]  # (kind, model, result or None for done)


async def consume_stream_jsonl(
    out_q: asyncio.Queue[Event],
    total_runners: int,
    filtered: list[str],
    *,
    tags: dict[str, str] | None = None,
    infinite: bool = False,
) -> None:
    finished = 0
    while True:
        kind, mid, res = await out_q.get()
        if res is None:
            if not infinite:
                finished += 1
                if finished >= total_runners:
                    break
            continue
        ts_now = datetime.now(UTC)
        if res.ok:
            rec_ok = StreamRecordOK(
                ts=ts_now.timestamp(),
                model=mid,
                family=family_of(mid).value,
                kind=kind,
                ok=True,
                latency_s=res.latency_s,
                tags=tags or None,
            )
            raw = res.raw
            if raw is not None:
                if kind == "responses":
                    resp_obj = res.raw_responses()
                    if resp_obj is None:
                        raise TypeError("Expected ResponsesType for responses kind")
                    response_dict = resp_obj.model_dump(exclude_none=False)
                else:
                    chat_obj = res.raw_chat()
                    if chat_obj is None:
                        raise TypeError("Expected ChatCompletion for chat kind")
                    response_dict = chat_obj.model_dump(exclude_none=False)
                rec_ok.response = response_dict
                # Add string representation for LogQL
                rec_ok.response_str = json.dumps(response_dict, separators=(",", ":"))[
                    :500
                ]  # Truncate to 500 chars

            print(rec_ok.model_dump_json(), flush=True)
        else:
            classification = res.error_classification
            rec_err = StreamRecordError(
                ts=ts_now.timestamp(),
                model=mid,
                family=family_of(mid).value,
                kind=kind,
                ok=False,
                error=ErrorInfo(
                    type=(type(res.exc).__name__ if res.exc is not None else None),
                    message=res.error_message,
                    status_code=(
                        getattr(res.exc, "status_code", None)
                        if res.exc is not None
                        else None
                    ),
                    body=(
                        getattr(res.exc, "body", None) if res.exc is not None else None
                    ),
                    request_id=(
                        getattr(res.exc, "request_id", None)
                        if res.exc is not None
                        else None
                    ),
                    code=(classification[0].value if classification else None),
                ),
                tags=tags or None,
            )
            # Add error string for LogQL
            error_code = classification[0].value if classification else "UNKNOWN"
            error_msg = res.error_message or "Unknown error"
            rec_err.error_str = f"{error_code}: {error_msg}"[
                :200
            ]  # Truncate to 200 chars

            print(rec_err.model_dump_json(), flush=True)


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

    show_fatal = reactive(False)
    family_idx = reactive(0)

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
        # Accumulators/state used for the TUI view
        self.acc: dict[str, dict[str, list[ProbeResult]]] = {
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
        # Load past cached results before we start (do not swallow errors)
        self._load_past_results()
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
                self.acc[mid][kind].append(res)
                # Persist event to cache (raise on failure)
                _persist_result(res)
                # Write to database
                await _write_probe_result(res)
                if not res.ok:
                    classification = res.error_classification
                    if classification:
                        code, desc = classification
                        if code != ErrorCode.OTHER:
                            self.used_codes.setdefault(code.value, desc)
                        if code in FATAL_CODES:
                            self.fatal_by_mid[mid] = True
            self._render_view()
        # Final render to include failure summary and legend
        self._render_view(final=True)

    def _load_past_results(self) -> None:
        """Load past JSONL events from the cache and hydrate current view state.

        Only events for models present in this run (self.filtered) are applied.
        """
        if not _CACHE_FILE.exists():
            return
        with _CACHE_FILE.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                raw = json.loads(line)
                try:
                    record = ProbeRecord.model_validate(raw)
                except Exception:
                    continue
                mid = record.model
                if mid not in self.filtered:
                    continue
                kind = record.kind
                if kind not in ("responses", "chat"):
                    continue
                try:
                    result = ProbeResult.from_record(record)
                except Exception:
                    # Skip corrupt or unparseable cache entries strictly
                    continue
                self.acc[mid][kind].append(result)
                if not result.ok:
                    classification = result.error_classification
                    if classification:
                        code, desc = classification
                        if code != ErrorCode.OTHER:
                            self.used_codes.setdefault(code.value, desc)
                        if code in FATAL_CODES:
                            self.fatal_by_mid[mid] = True

    def action_toggle_fatal(self) -> None:
        self.show_fatal = not self.show_fatal
        self._render_view()

    async def action_quit(self) -> None:
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
        if 0 <= self.family_idx < len(self.family_choices):
            return cast(Family | None, self.family_choices[self.family_idx])
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
        # Build tables for the TUI view, applying fatal filter
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


# ---------- History lookups (Postgres-backed) --------------------------------------


@dataclass(frozen=True)
class KindHistory:
    last_seen: datetime | None = None
    last_ok: datetime | None = None


HistoryKey = tuple[str, str]


@dataclass(frozen=True)
class HistorySnapshot:
    data: Mapping[HistoryKey, KindHistory]

    def get(self, model: str, kind: str) -> KindHistory | None:
        return self.data.get((model, kind))


PROBE_KINDS: tuple[ProbeKind, ...] = ("responses", "chat")
HISTORY_LOOKBACK = max(OK_LOOKBACK, MIN_INTERVAL)


async def fetch_model_history(
    models: Sequence[str],
    *,
    kinds: Sequence[str] | None = None,
    now: datetime | None = None,
) -> HistorySnapshot:
    """Fetch per-model, per-kind history windows directly from Postgres."""

    if not models:
        return HistorySnapshot(MappingProxyType({}))

    kinds = tuple(kinds or PROBE_KINDS)
    if not kinds:
        return HistorySnapshot(MappingProxyType({}))

    now = now or datetime.now(UTC)
    window_start = now - HISTORY_LOOKBACK

    pool = await _get_db_pool()
    query = """
        SELECT
            model,
            kind,
            max(start_time) AS last_seen,
            max(start_time) FILTER (WHERE success) AS last_ok
        FROM probe_results
        WHERE model = ANY($1::text[])
          AND kind = ANY($2::text[])
          AND start_time >= $3
        GROUP BY model, kind
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, list(models), list(kinds), window_start)

    history: dict[HistoryKey, KindHistory] = {}
    for row in rows:
        history[(row["model"], row["kind"])] = KindHistory(
            last_seen=row["last_seen"],
            last_ok=row["last_ok"],
        )
    return HistorySnapshot(MappingProxyType(history))


def classify_status(
    info: KindHistory | None,
    *,
    now: datetime,
) -> tuple[bool, bool]:
    """Return (recent_ok, seen_recent) flags for a given history record."""

    last_seen = info.last_seen if info else None
    last_ok = info.last_ok if info else None
    seen_recent = bool(last_seen and last_seen > now - MIN_INTERVAL)
    recent_ok = bool(last_ok and last_ok > now - OK_LOOKBACK)
    return recent_ok, seen_recent


def make_limiter(qps: float) -> AsyncLimiter:
    qps = max(float(qps), 0.001)
    return AsyncLimiter(int(qps), 1.0) if qps >= 1.0 else AsyncLimiter(1, 1.0 / qps)


def parse_tags_cli(items: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for value in items:
        if isinstance(value, str) and "=" in value:
            key, val = value.split("=", 1)
            if key:
                out[key] = val
    return out


def build_models_summary(
    filtered: Sequence[str],
    history: HistorySnapshot,
    *,
    now: datetime,
) -> list[ModelSummary]:
    summary: list[ModelSummary] = []
    for mid in sorted(filtered, key=lambda m: (priority_index(m), m)):
        per_kind: list[KindStatusEntry] = []
        for kind in PROBE_KINDS:
            recent_ok, _ = classify_status(history.get(mid, kind), now=now)
            per_kind.append(KindStatusEntry(kind=kind, recent_ok=recent_ok))
        summary.append(
            ModelSummary(
                model=mid,
                family=family_of(mid).value,
                recent_ok=any(entry.recent_ok for entry in per_kind),
                recent_ok_by_kind=tuple(per_kind),
            )
        )
    return summary


def list_models_json(
    filtered: Sequence[str],
    history: HistorySnapshot,
    *,
    now: datetime,
) -> str:
    records = [
        entry.model_dump() for entry in build_models_summary(filtered, history, now=now)
    ]
    return json.dumps(records, indent=2)


def emit_models_listing(
    summary: Sequence[ModelSummary],
    *,
    tags: dict[str, str] | None = None,
    persist: bool = False,
) -> None:
    if not summary:
        return
    ts = datetime.now(UTC)
    tag_payload = tags or None
    lines: list[str] = []
    for info in summary:
        record = ModelListRecord(
            ts=ts.timestamp(),
            model=info.model,
            family=info.family,
            recent_ok=info.recent_ok,
            recent_ok_by_kind=list(info.recent_ok_by_kind) or None,
            tags=tag_payload,
        )
        line = record.model_dump_json()
        print(line, flush=True)
        lines.append(line)
    if persist and lines:
        _ensure_cache_dir()
        with _CACHE_FILE.open("a", encoding="utf-8") as fh:
            for line in lines:
                fh.write(line + "\n")


# ---------- Runner orchestration -------------------------------------------


async def run_probe_series(
    *,
    kind: ProbeKind,
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
    desc = (
        "Filter and test OpenAI models with a smart, history‑aware policy.\n\n"
        "Default behavior: prioritize models recently OK (from cache), slowly sample others;\n"
        "skip models seen very recently; apply fast/slow QPS and repeats.\n\n"
        "Run modes:\n"
        "  - TUI (default): live Rich/Textual tables with grouped stats.\n"
        "  - --stream: print JSONL events suitable for Loki/Grafana (no summary).\n"
        "  - --list-models: print filtered models with recent_ok flag and exit.\n"
    )
    epilog = (
        "Examples:\n"
        "  adgn-openai-probe --list-models\n"
        "  adgn-openai-probe --stream --tag env=prod --tag job=openai-probe\n"
        "  adgn-openai-probe -c 64 -r 5 --stream\n"
    )
    parser = argparse.ArgumentParser(
        description=desc,
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--sample", type=int, default=0, help="Randomly sample N models (0 = use all)"
    )
    parser.add_argument(
        "--concurrency", type=int, default=128, help="Max concurrent requests"
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=5,
        help="Repeats per probe per model (default: 5)",
    )
    parser.add_argument("--max-qps", type=float, default=0.3, help="Global max QPS")
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
    parser.add_argument(
        "--tag",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Add a tag key=value to JSON output (repeatable)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=100,
        help="Maximum number of output tokens for API calls (default: 100)",
    )
    parser.add_argument(
        "--fast-qps",
        type=float,
        required=True,
        help="Requests per second for fast scheduler loops",
    )
    parser.add_argument(
        "--slow-qps",
        type=float,
        required=True,
        help="Requests per second for slow scheduler loops",
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="List models (after filters) with history classification and exit",
    )
    parser.add_argument(
        "--drop-regex",
        type=str,
        default=None,
        help=(
            "Regex for excluding model IDs (e.g., use (?i) for case-insensitive). "
            "If omitted, no regex-based dropping is applied."
        ),
    )
    return parser.parse_args(argv)


async def _async_main() -> None:
    args = parse_args()
    # Smart policy uses separate fast/slow limiters; no single global limiter here

    # Initialize database connection — fail fast if unavailable
    try:
        await _init_database()
        print("Database initialized successfully", file=sys.stderr)
    except Exception as e:
        print(f"ERROR: Database initialization failed: {e}", file=sys.stderr)
        sys.exit(1)

    tag_map = parse_tags_cli(args.tag)
    # Compile drop regex from CLI (no default; explicit only)
    global DROP_MODEL_ID_RE
    if args.drop_regex:
        try:
            DROP_MODEL_ID_RE = re.compile(args.drop_regex)
        except re.error as re_err:
            print(f"Invalid --drop-regex: {re_err}", file=sys.stderr)
            sys.exit(2)
    async_client = _get_async_openai()
    if not args.stream:
        print("Fetching model list …", file=sys.stderr)
    resp = await async_client.models.list()
    model_ids = [m.id for m in resp.data]
    if not args.stream:
        print(f"Total models from API: {len(model_ids)}", file=sys.stderr)

    # Filtering
    filtered = [mid for mid in model_ids if not is_excluded(mid)]
    if args.family:
        filtered = [mid for mid in filtered if family_of(mid).value == args.family]
    if not args.stream:
        print(f"After filtering rules: {len(filtered)}", file=sys.stderr)

    if args.list_models:
        now_summary = datetime.now(UTC)
        history = await fetch_model_history(filtered, now=now_summary)
        summary = build_models_summary(filtered, history, now=now_summary)
        emit_models_listing(summary, tags=tag_map, persist=True)
        return

    # Optional sampling
    if args.sample and args.sample < len(filtered):
        filtered = random.sample(filtered, args.sample)
        if not args.stream:
            print(f"Sub-sampled to {len(filtered)} models (random)", file=sys.stderr)

    if args.stream:
        now_summary = datetime.now(UTC)
        history = await fetch_model_history(filtered, now=now_summary)
        summary_for_stream = build_models_summary(filtered, history, now=now_summary)
        emit_models_listing(summary_for_stream, tags=tag_map, persist=True)

    # Probe specs
    responses_spec = ProbeSpec(
        name="responses", create=partial(_create_responses, max_tokens=args.max_tokens)
    )
    chat_spec = ProbeSpec(
        name="chat", create=partial(_create_chat, max_tokens=args.max_tokens)
    )

    if args.stream and args.continuous:
        # Functional, low-state continuous schedulers
        sem = asyncio.Semaphore(max(args.concurrency, 1))
        limiter_fast = make_limiter(args.fast_qps)
        limiter_slow = make_limiter(args.slow_qps)
        current_models = list(filtered)

        async def models_refresher() -> None:
            nonlocal current_models
            while True:
                try:
                    await asyncio.sleep(21600)  # refresh every 6 hours
                    resp2 = await async_client.models.list()
                    mids = [m.id for m in resp2.data]
                    mids = [mid for mid in mids if not is_excluded(mid)]
                    if args.family:
                        mids = [
                            mid for mid in mids if family_of(mid).value == args.family
                        ]
                    current_models = mids
                    now_refresh = datetime.now(UTC)
                    history_refresh = await fetch_model_history(mids, now=now_refresh)
                    summary_refresh = build_models_summary(
                        mids, history_refresh, now=now_refresh
                    )
                    emit_models_listing(summary_refresh, tags=tag_map, persist=True)
                    _log_event("models_refresh", count=len(mids))
                except Exception as e:
                    _log_event("models_refresh_error", error=str(e))
                    await asyncio.sleep(10)

        slow_rr: dict[ProbeKind, int] = {"responses": 0, "chat": 0}

        async def scheduler(
            kind: ProbeKind, limiter: AsyncLimiter, want_fast: bool
        ) -> None:
            spec = responses_spec if kind == "responses" else chat_spec
            while True:
                try:
                    async with limiter:
                        now_dt = datetime.now(UTC)
                        models_snapshot = list(current_models)
                        if not models_snapshot:
                            await asyncio.sleep(1)
                            continue
                        history_kind = await fetch_model_history(
                            models_snapshot, kinds=(kind,), now=now_dt
                        )
                        eligible_models: list[str] = []
                        for mid in models_snapshot:
                            recent_ok, seen_recent = classify_status(
                                history_kind.get(mid, kind), now=now_dt
                            )
                            if seen_recent:
                                continue
                            if want_fast:
                                if recent_ok:
                                    eligible_models.append(mid)
                            else:
                                if not recent_ok:
                                    eligible_models.append(mid)
                        if not eligible_models:
                            await asyncio.sleep(0.25)
                            continue
                        if want_fast:
                            pick = random.choice(eligible_models)
                        else:
                            mids_sorted = sorted(
                                eligible_models, key=lambda m: (priority_index(m), m)
                            )
                            idx = slow_rr[kind] % len(mids_sorted)
                            slow_rr[kind] += 1
                            pick = mids_sorted[idx]
                        _log_event("call_start", kind=kind, model=pick)
                        async with sem:
                            res = await _probe_once(
                                async_client,
                                model_id=pick,
                                spec=spec,
                                limiter=make_limiter(10_000),  # outer limiter gates QPS
                            )
                        _log_event("call_end", kind=kind, model=pick, ok=res.ok)
                        # Write to database
                        await _write_probe_result(res)
                        # Emit event
                        await stream_q.put((kind, pick, res))
                except Exception as e:
                    _log_event("scheduler_error", kind=kind, error=str(e))
                    await asyncio.sleep(1)

        stream_q: asyncio.Queue[Event] = asyncio.Queue()
        tasks = [
            asyncio.create_task(models_refresher()),
            asyncio.create_task(scheduler("responses", limiter_fast, True)),
            asyncio.create_task(scheduler("chat", limiter_fast, True)),
            asyncio.create_task(scheduler("responses", limiter_slow, False)),
            asyncio.create_task(scheduler("chat", limiter_slow, False)),
        ]
        for t in tasks:
            t.add_done_callback(
                lambda fut: _log_event(
                    "task_done", error=str(fut.exception()) if fut.exception() else None
                )
            )
        # Stream indefinitely
        await consume_stream_jsonl(
            stream_q, 0, current_models, tags=tag_map, infinite=True
        )
    else:
        # Fallback to original per-model run for TUI / non-continuous
        sem = asyncio.Semaphore(max(args.concurrency, 1))
        prioritized = sorted(filtered, key=lambda mid: (priority_index(mid), mid))
        event_q: asyncio.Queue[Event] = asyncio.Queue()
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
                        limiter=make_limiter(args.fast_qps),
                        client=async_client,
                        out_q=event_q,
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
                        limiter=make_limiter(args.fast_qps),
                        client=async_client,
                        out_q=event_q,
                    )
                )
            )

        total_runners = len(runners)
        if args.stream:
            await consume_stream_jsonl(event_q, total_runners, filtered, tags=tag_map)
        else:
            disp_repeats = max(int(args.repeats), 1)
            await consume_stream_textual(
                event_q,
                total_runners,
                filtered,
                repeats=disp_repeats,
                show_fatal=bool(getattr(args, "show_fatal", False)),
            )

        await asyncio.gather(*runners, return_exceptions=True)


def main() -> None:
    async def start_health_server() -> None:
        async def _health(request: web.Request) -> web.Response:  # type: ignore[override]
            return web.Response(text="OK")

        async def _metrics(request: web.Request) -> web.Response:  # type: ignore[override]
            return web.Response(
                text="Metrics endpoint disabled (Prometheus removed)", status=404
            )

        app = web.Application()
        app.router.add_get(HEALTH_PATH, _health)
        app.router.add_get(METRICS_PATH, _metrics)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host="0.0.0.0", port=HEALTH_PORT)
        await site.start()

    async def entry() -> None:
        await start_health_server()
        await _async_main()

    asyncio.run(entry())


if __name__ == "__main__":
    main()
