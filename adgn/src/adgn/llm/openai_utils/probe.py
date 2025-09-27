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
from collections.abc import Awaitable, Callable, Sequence
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
from pathlib import Path

from aiolimiter import AsyncLimiter
from adgn.llm.client_factory import _get_async_openai as _factory_async_client
from openai import AsyncOpenAI
from openai._exceptions import APIStatusError
from openai.types.responses.function_tool_param import FunctionToolParam
from openai.types.responses.tool_choice_function_param import ToolChoiceFunctionParam
from rich import box
from rich.console import Group
from rich.table import Table
from platformdirs import user_cache_dir
from pydantic import BaseModel
from aiohttp import web
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static
from textual.reactive import reactive
from textual.events import Key
import asyncpg


# ---------- Constants & utilities ----------

INF: float = float("inf")

# Additional exclusion regex for model IDs (beyond family drop rules)
# Adjust this to cover fine-tunes and other unwanted variants.
EXCLUDE_MODEL_ID_RE = re.compile(
    r"(?i)(:ft:|\bft-\b|\b-ft\b|fine[-_ ]?tune|fine[-_ ]?tuned)"
)

# Smart policy constants (hardcoded)
OK_LOOKBACK = timedelta(hours=24)
MIN_INTERVAL = timedelta(minutes=10)
SLOW_PROB = 0.1
FAST_QPS = 0.3
SLOW_QPS = 0.05
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
    kind: str  # "responses" | "chat"
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
    """Initialize database schema if needed."""
    pool = await _get_db_pool()

    schema_sql = """
    -- Create table if not exists
    CREATE TABLE IF NOT EXISTS probe_results (
      -- Timing
      start_time TIMESTAMPTZ NOT NULL,
      end_time TIMESTAMPTZ NOT NULL,
      latency_s DOUBLE PRECISION NOT NULL,

      -- Model info
      model TEXT NOT NULL,
      family TEXT NOT NULL,
      kind TEXT NOT NULL,  -- 'chat' or 'responses'

      -- Result
      success BOOLEAN NOT NULL,

      -- Error details (NULL if success)
      error_code TEXT,
      error_message TEXT,
      error_status INT,

      -- Chat API response fields (NULL unless kind='chat' and success=true)
      chat_response_content TEXT,
      chat_response_role TEXT,
      chat_finish_reason TEXT,
      chat_completion_tokens INT,
      chat_prompt_tokens INT,

      -- Responses API fields (NULL unless kind='responses' and success=true)
      responses_text TEXT,
      responses_finish_reason TEXT,
      responses_tokens INT,

      -- Request metadata
      request_id TEXT,
      api_key_suffix TEXT
    );

    -- Create hypertable if TimescaleDB extension is available
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
            -- Only create hypertable if it doesn't exist
            IF NOT EXISTS (SELECT 1 FROM timescaledb_information.hypertables WHERE hypertable_name = 'probe_results') THEN
                PERFORM create_hypertable('probe_results', 'start_time');
            END IF;
        END IF;
    END
    $$;

    -- Create indexes if they don't exist
    CREATE INDEX IF NOT EXISTS idx_probe_results_model_time ON probe_results (model, start_time DESC);
    CREATE INDEX IF NOT EXISTS idx_probe_results_family_kind_time ON probe_results (family, kind, start_time DESC);
    CREATE INDEX IF NOT EXISTS idx_probe_results_error ON probe_results (success, start_time DESC) WHERE NOT success;
    CREATE INDEX IF NOT EXISTS idx_probe_results_error_code ON probe_results (error_code, start_time DESC) WHERE error_code IS NOT NULL;
    """

    async with pool.acquire() as conn:
        await conn.execute(schema_sql)


async def _write_probe_result(res: "ProbeResult") -> None:
    """Write probe result to TimescaleDB."""
    if not res.start_ts or not res.end_ts:
        return  # Skip if missing timing data

    pool = await _get_db_pool()

    # Extract response data based on API type
    chat_content = None
    chat_role = None
    chat_finish_reason = None
    chat_completion_tokens = None
    chat_prompt_tokens = None
    responses_text = None
    responses_finish_reason = None
    responses_tokens = None

    if res.ok and res.raw:
        # Store the full response JSON
        import json
        if hasattr(res.raw, 'model_dump'):
            response_json = json.dumps(res.raw.model_dump(exclude_none=False), indent=None, separators=(',', ':'))
        else:
            response_json = json.dumps(res.raw, indent=None, separators=(',', ':'))

        if res.kind == "chat":
            # Store full JSON and extract metadata fields
            chat_content = response_json
            if hasattr(res.raw, 'choices') and res.raw.choices:
                choice = res.raw.choices[0]
                if hasattr(choice, 'message'):
                    chat_role = choice.message.role
                    chat_finish_reason = choice.finish_reason
            if hasattr(res.raw, 'usage'):
                chat_completion_tokens = res.raw.usage.completion_tokens
                chat_prompt_tokens = res.raw.usage.prompt_tokens
        elif res.kind == "responses":
            # Store full JSON and extract metadata fields
            responses_text = response_json
            if hasattr(res.raw, 'finish_reason'):
                responses_finish_reason = res.raw.finish_reason
            # Note: responses API may not have token counts in the same format

    # Extract error information
    error_code = None
    error_message = None
    error_status = None
    if not res.ok and res.exc:
        error_message = str(res.exc)
        if hasattr(res.exc, 'status_code'):
            error_status = res.exc.status_code
        # Classify error
        classification = res.error_classification
        if classification:
            error_code = classification[0].value

    # Get API key suffix
    api_key_suffix = None
    # Could extract from client if needed - for now skip

    # Get request ID
    request_id = None
    if hasattr(res.exc, 'request_id'):
        request_id = res.exc.request_id
    elif res.ok and res.raw and hasattr(res.raw, 'id'):
        request_id = res.raw.id

    insert_sql = """
    INSERT INTO probe_results (
        start_time, end_time, latency_s, model, family, kind, success,
        error_code, error_message, error_status,
        chat_response_content, chat_response_role, chat_finish_reason,
        chat_completion_tokens, chat_prompt_tokens,
        responses_text, responses_finish_reason, responses_tokens,
        request_id, api_key_suffix
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20)
    """

    async with pool.acquire() as conn:
        await conn.execute(
            insert_sql,
            res.start_ts,          # start_time
            res.end_ts,            # end_time
            res.latency_s,         # latency_s
            res.model_id,          # model
            family_of(res.model_id).value,  # family
            res.kind,              # kind
            res.ok,                # success
            error_code,            # error_code
            error_message,         # error_message
            error_status,          # error_status
            chat_content,          # chat_response_content
            chat_role,             # chat_response_role
            chat_finish_reason,    # chat_finish_reason
            chat_completion_tokens, # chat_completion_tokens
            chat_prompt_tokens,    # chat_prompt_tokens
            responses_text,        # responses_text
            responses_finish_reason, # responses_finish_reason
            responses_tokens,      # responses_tokens
            request_id,            # request_id
            api_key_suffix,        # api_key_suffix
        )


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


class ModelListRecord(BaseModel):
    ts: float
    type: Literal["models"] = "models"
    source: str = "adgn-openai-probe"
    model: str
    family: str
    recent_ok: bool
    tags: dict[str, str] | None = None


# ---------- Data classes ----------


@dataclass(frozen=True)
class ProbeResult:
    model_id: str
    kind: str
    ok: bool
    exc: BaseException | None = None
    raw: Any | None = None
    start_ts: datetime | None = None
    end_ts: datetime | None = None
    latency_override_s: float | None = None

    @classmethod
    def success(
        cls,
        *,
        model_id: str,
        kind: str,
        raw: Any,
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
        kind: str,
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
                    return _snippet_from_responses(self.raw)
                if self.kind == "chat":
                    return _snippet_from_chat(self.raw)
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
            raw_obj = self.raw
            if hasattr(raw_obj, "model_dump"):
                payload = raw_obj.model_dump(exclude_none=False)
            else:
                payload = raw_obj
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
        raw = record.response if record.ok else None
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


@dataclass(frozen=True)
class ProbeSpec:
    name: str
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


def _snippet_from_responses(resp) -> str:
    # Accept typed response or plain dict
    if hasattr(resp, "output_text"):
        txt = getattr(resp, "output_text")
        if txt:
            return _squeeze_one_line(txt)
    # Fallback: inspect for output blocks and tool/function calls
    if hasattr(resp, "model_dump"):
        data = resp.model_dump(exclude_none=True)
    elif isinstance(resp, dict):
        data = resp
    else:
        raise TypeError("Unsupported response type for responses snippet extraction")
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
    if hasattr(resp, "model_dump"):
        data = resp.model_dump(exclude_none=True)
    elif isinstance(resp, dict):
        data = resp
    else:
        raise TypeError("Unsupported response type for chat snippet extraction")
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
    if hasattr(resp, "choices"):
        content = resp.choices[0].message.content if resp.choices else None
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
    LEGACY_ENGINES = "legacy-engines"
    GPT_3 = "gpt-3"
    GPT_4O = "gpt-4o"
    GPT_41_MINI_NANO = "gpt-4.1-mini-nano"
    GPT_5_MINI_NANO = "gpt-5-mini-nano"
    O_MINI = "o-mini"
    RM_MODELS = "rm-models"
    # Kept/classifiable families
    GPT_5 = "gpt-5"
    O3 = "o3"
    O4_MINI = "o4-mini"
    O1 = "o1"
    GPT_41 = "gpt-4.1"
    OTHER = "other"


FAMILY_RULES: dict[Family, str] = {
    # Dropped families (filtered out)
    Family.LEGACY_ENGINES: r"\b(ada|curie|babbage|davinci|d1[26])\b",
    Family.GPT_3: r"\bgpt[-_]?3(\b|[.-])",
    Family.GPT_4O: r"(?<![a-z0-9])gpt[-_]?4o(?![a-z0-9])",
    Family.GPT_41_MINI_NANO: r"\bgpt[-_]?4\.1-(mini|nano)\b",
    Family.GPT_5_MINI_NANO: r"\bgpt[-_]?5-(mini|nano)\b",
    Family.O_MINI: r"\bo[13]-mini\b",
    Family.RM_MODELS: r"-rm-",
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
    if family_of(mid) in FAMILY_DROP:
        return True
    if EXCLUDE_MODEL_ID_RE.search(mid):
        return True
    return False


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


Event = tuple[str, str, ProbeResult | None]  # (kind, model, result or None for done)


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
                response_dict = (
                    raw.model_dump(exclude_none=False)
                    if hasattr(raw, "model_dump")
                    else raw
                )
                rec_ok.response = response_dict
                # Add string representation for LogQL
                import json
                rec_ok.response_str = json.dumps(response_dict, separators=(",", ":"))[:500]  # Truncate to 500 chars

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
            rec_err.error_str = f"{error_code}: {error_msg}"[:200]  # Truncate to 200 chars


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
                result = ProbeResult.from_record(record)
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
        if 0 <= self.family_idx < len(self.family_choices):
            return self.family_choices[self.family_idx]
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


# ---------- History index (from cache) --------------------------------------


class ModelHistory(BaseModel):
    last_seen: datetime | None = None
    last_ok: datetime | None = None


def _parse_iso_ts(s: str | None) -> datetime | None:
    if not s or not isinstance(s, str):
        return None
    return datetime.fromisoformat(s)


def load_history_index() -> dict[str, ModelHistory]:
    """Build a history index from the JSONL cache.

    Returns per-model last_seen and last_ok UTC datetimes. Missing file yields empty index.
    """
    idx: dict[str, ModelHistory] = {}
    if not _CACHE_FILE.exists():
        return idx
    with _CACHE_FILE.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if not isinstance(rec, dict) or rec.get("type") != "event":
                continue
            mid = rec.get("model")
            if not isinstance(mid, str):
                continue
            ts = _parse_iso_ts(rec.get("ts"))
            ok = bool(rec.get("ok", False))
            mh = idx.setdefault(mid, ModelHistory())
            if ts and (mh.last_seen is None or ts > mh.last_seen):
                mh.last_seen = ts
            if ok and ts and (mh.last_ok is None or ts > mh.last_ok):
                mh.last_ok = ts
    return idx


# ---------- Selection & rate limiting helpers -------------------------------


def classify_model(
    mid: str, hist: dict[str, "ModelHistory"], now: datetime
) -> tuple[bool, bool]:
    """Return (recent_ok, seen_recent) for a model based on history and constants.

    - recent_ok: last OK within OK_LOOKBACK
    - seen_recent: any event within MIN_INTERVAL (used to skip probing)
    """
    mh = hist.get(mid)
    last_seen_recent = False
    recent_ok = False
    if mh and mh.last_seen is not None and mh.last_seen > now - MIN_INTERVAL:
        last_seen_recent = True
    if mh and mh.last_ok is not None and mh.last_ok > now - OK_LOOKBACK:
        recent_ok = True
    return recent_ok, last_seen_recent


def select_models(
    filtered: list[str], hist: dict[str, "ModelHistory"], now: datetime
) -> tuple[list[str], list[str]]:
    """Partition filtered models into (selected_fast, selected_slow).

    - Fast: models recently OK and not seen within MIN_INTERVAL
    - Slow: sample from others with probability SLOW_PROB (ensure at least one if any)
    """
    selected_fast: list[str] = []
    selected_slow: list[str] = []
    slow_pool: list[str] = []
    for mid in filtered:
        recent_ok, seen_recent = classify_model(mid, hist, now)
        if seen_recent:
            continue
        if recent_ok:
            selected_fast.append(mid)
        else:
            slow_pool.append(mid)
            if random.random() < SLOW_PROB:
                selected_slow.append(mid)
    if slow_pool and not selected_slow:
        selected_slow.append(random.choice(slow_pool))

    selected_fast.sort(key=lambda m: (priority_index(m), m))
    selected_slow.sort(key=lambda m: (priority_index(m), m))
    return selected_fast, selected_slow


def make_limiter(qps: float) -> AsyncLimiter:
    qps = max(float(qps), 0.001)
    return AsyncLimiter(int(qps), 1.0) if qps >= 1.0 else AsyncLimiter(1, 1.0 / qps)


def parse_tags_cli(items: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for t in items:
        if isinstance(t, str) and "=" in t:
            k, v = t.split("=", 1)
            if k:
                out[k] = v
    return out


def build_models_summary(
    filtered: list[str], hist: dict[str, "ModelHistory"]
) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    summary: list[dict[str, Any]] = []
    for mid in sorted(filtered, key=lambda m: (priority_index(m), m)):
        ro, _ = classify_model(mid, hist, now)
        summary.append(
            {
                "model": mid,
                "family": family_of(mid).value,
                "recent_ok": ro,
            }
        )
    return summary


def list_models_json(filtered: list[str], hist: dict[str, "ModelHistory"]) -> str:
    return json.dumps(build_models_summary(filtered, hist), indent=2)


def emit_models_listing(
    summary: list[dict[str, Any]],
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
            model=info.get("model", ""),
            family=str(info.get("family", "")),
            recent_ok=bool(info.get("recent_ok", False)),
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
        "--list-models",
        action="store_true",
        help="List models (after filters) with history classification and exit",
    )
    return parser.parse_args(argv)


async def _async_main() -> None:
    args = parse_args()
    # Smart policy uses separate fast/slow limiters; no single global limiter here

    # Initialize database connection and schema
    try:
        await _init_database()
        print("Database initialized successfully", file=sys.stderr)
    except Exception as e:
        print(f"Warning: Database initialization failed: {e}", file=sys.stderr)
        print("Continuing without database writes", file=sys.stderr)

    tag_map = parse_tags_cli(args.tag)
    async_client = _factory_async_client()
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

    # History-driven classification
    hist = load_history_index()

    if args.list_models:
        summary = build_models_summary(filtered, hist)
        emit_models_listing(summary, tags=tag_map, persist=True)
        return

    # Optional sampling
    if args.sample and args.sample < len(filtered):
        filtered = random.sample(filtered, args.sample)
        if not args.stream:
            print(f"Sub-sampled to {len(filtered)} models (random)", file=sys.stderr)

    if args.stream:
        summary_for_stream = build_models_summary(filtered, hist)
        emit_models_listing(summary_for_stream, tags=tag_map, persist=True)

    # Probe specs
    responses_spec = ProbeSpec(name="responses", create=partial(_create_responses, max_tokens=args.max_tokens))
    chat_spec = ProbeSpec(name="chat", create=partial(_create_chat, max_tokens=args.max_tokens))

    if args.stream and args.continuous:
        # Functional, low-state continuous schedulers
        sem = asyncio.Semaphore(max(args.concurrency, 1))
        limiter_fast = make_limiter(FAST_QPS)
        limiter_slow = make_limiter(SLOW_QPS)
        current_models = list(filtered)

        async def models_refresher() -> None:
            nonlocal current_models, hist
            while True:
                await asyncio.sleep(21600)  # refresh every 6 hours
                resp2 = await async_client.models.list()
                mids = [m.id for m in resp2.data]
                mids = [mid for mid in mids if not is_excluded(mid)]
                if args.family:
                    mids = [mid for mid in mids if family_of(mid).value == args.family]
                current_models = mids
                hist = load_history_index()
                summary_refresh = build_models_summary(mids, hist)
                emit_models_listing(summary_refresh, tags=tag_map, persist=True)

        def eligible(now_dt: datetime, mid: str, want_fast: bool) -> bool:
            ro, seen_recent = classify_model(mid, hist, now_dt)
            if seen_recent:
                return False
            return ro if want_fast else not ro

        slow_rr: dict[str, int] = {"responses": 0, "chat": 0}

        async def scheduler(kind: str, limiter: AsyncLimiter, want_fast: bool) -> None:
            spec = responses_spec if kind == "responses" else chat_spec
            while True:
                async with limiter:
                    now_dt = datetime.now(UTC)
                    mids = [m for m in current_models if eligible(now_dt, m, want_fast)]
                    if not mids:
                        continue
                    if want_fast:
                        pick = random.choice(mids)
                    else:
                        mids_sorted = sorted(mids, key=lambda m: (priority_index(m), m))
                        idx = slow_rr[kind] % len(mids_sorted)
                        slow_rr[kind] += 1
                        pick = mids_sorted[idx]
                    async with sem:
                        res = await _probe_once(
                            async_client,
                            model_id=pick,
                            spec=spec,
                            limiter=make_limiter(10_000),  # outer limiter gates QPS
                        )
                    # Update history index from result
                    ts_now = datetime.now(UTC)
                    mh = hist.setdefault(pick, ModelHistory())
                    mh.last_seen = ts_now
                    if res.ok:
                        mh.last_ok = ts_now
                    # Write to database
                    await _write_probe_result(res)
                    # Emit event
                    await stream_q.put((kind, pick, res))

        stream_q: asyncio.Queue[Event] = asyncio.Queue()
        asyncio.create_task(models_refresher())
        asyncio.create_task(scheduler("responses", limiter_fast, True))
        asyncio.create_task(scheduler("chat", limiter_fast, True))
        asyncio.create_task(scheduler("responses", limiter_slow, False))
        asyncio.create_task(scheduler("chat", limiter_slow, False))
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
                        limiter=make_limiter(FAST_QPS),
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
                        limiter=make_limiter(FAST_QPS),
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
            return web.Response(text="Metrics endpoint disabled (Prometheus removed)", status=404)

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
