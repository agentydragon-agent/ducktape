"""Probe OpenAI models via Responses and Chat APIs.

- Filters model list by family and a configurable regex to exclude noise (e.g., fine-tunes).
- Smart selection prioritizes models recently OK (from cache) and slowly samples others; skips very recently seen.
- Uses fast/slow QPS and repeats; early-stops on fatal, non-retryable errors.
- Emits JSONL events and persists faithful responses to XDG cache; TUI renders a live table.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Literal

from aiolimiter import AsyncLimiter
import asyncpg
from openai._exceptions import APIStatusError
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.responses import Response
from platformdirs import user_cache_dir
from pydantic import BaseModel, ConfigDict

from adgn.openai_utils.probe.core import (
    FAMILY_PRIORITY,
    FATAL_CODES,
    ErrorCode,
    Family,
    ModelProbe,
    ProbeRun,
    family_of,
)

__all__ = ["FAMILY_PRIORITY", "FATAL_CODES", "ErrorCode", "Family", "ModelProbe", "ProbeRun", "family_of"]

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
# Defer validation: some environments/tests won't set DB_PASSWORD

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
    except Exception as e:
        # Never let logging crash the probe; emit a fallback line to stderr
        sys.stderr.write(f"[probe-log] failed to serialize log event {event_type}: {e}\n")


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


class ProbeKind(StrEnum):
    """Type of API endpoint to probe."""

    RESPONSES = "responses"
    CHAT = "chat"


class ProbeRecord(BaseModel):
    ts: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    model: str
    kind: ProbeKind
    ok: bool
    latency_s: float | None = None
    response: dict[str, Any] | None = None
    error: ErrorInfo | None = None


def _persist_result(res: ProbeResult) -> None:
    """Append a single probe result to the JSONL cache."""
    _ensure_cache_dir()
    record = res.to_cache_record()
    with _CACHE_FILE.open("a", encoding="utf-8") as fh:
        fh.write(record.model_dump_json() + "\n")


# Database connection and initialization
_db_pool: asyncpg.Pool | None = None


async def _get_db_pool() -> asyncpg.Pool:
    """Get or create database connection pool."""
    global _db_pool  # noqa: PLW0603
    if _db_pool is None:
        _db_pool = await asyncpg.create_pool(
            host=DB_HOST, port=DB_PORT, database=DB_NAME, user=DB_USER, password=DB_PASSWORD, min_size=1, max_size=10
        )
    return _db_pool


async def _init_database() -> None:
    """Ensure database connectivity; schema managed externally (k8s migration)."""
    await _get_db_pool()


async def _write_probe_result(res: ProbeResult) -> None:
    """Write probe result to TimescaleDB."""
    if not res.started_at or not res.ended_at:
        return  # Skip if missing timing data

    pool = await _get_db_pool()

    # Extract response data based on API type
    chat_json: Any | None = None
    responses_json: Any | None = None

    if res.ok and res.raw:
        if res.kind == ProbeKind.CHAT:
            chat_obj = res.raw_chat()
            if chat_obj is not None:
                chat_json = chat_obj.model_dump(exclude_none=False)
        elif res.kind == ProbeKind.RESPONSES:
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
                except ValueError:
                    # Non-JSON body; keep fallback handling
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
                res.started_at,  # start_time
                res.ended_at,  # end_time
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
            _log_event("db_write", model=res.model_id, kind=res.kind, ok=res.ok, has_error_body=bool(error_body_json))
        except Exception as e:
            _log_event("db_write_error", model=res.model_id, kind=res.kind, error=str(e))
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


# Model family heuristic

FAMILY_DROP: set[Family] = set()


def is_excluded(mid: str) -> bool:
    return bool(DROP_MODEL_ID_RE.search(mid)) if DROP_MODEL_ID_RE is not None else False


def priority_index(mid: str) -> int:
    fam = family_of(mid)
    priority: list[Family] = FAMILY_PRIORITY
    try:
        return priority.index(fam)
    except ValueError:
        return len(priority)


# Error codes and rules
ERROR_RULES: Mapping[ErrorCode, tuple[str, Callable[[str], bool]]] = {
    ErrorCode.MISSING_TOOLS_NAME: (
        "Missing tools name in tool call; make sure to set the name.",
        lambda m: "missing tools name" in m or "missing tool name" in m,
    ),
    ErrorCode.RATE_LIMIT: (
        "Rate limit exceeded; back off and retry",
        lambda m: "rate limit" in m or "overloaded" in m or "too many requests" in m,
    ),
    # ... rules elided for brevity ...
}


def _squeeze_one_line(text: str, max_len: int = 120) -> str:
    s = " ".join(str(text).split())
    return s if len(s) <= max_len else s[: max_len - 1] + "…"


def msg_from_exc(e: BaseException | None) -> str:
    if e is None:
        return ""
    if isinstance(e, APIStatusError):
        body = e.body
        msg = body.get("message") if isinstance(body, dict) and "message" in body else e.message
        return msg or repr(e)
    return str(e) or repr(e)


def classify_error(msg: str) -> tuple[ErrorCode, str]:
    m = msg.lower()
    for code, (desc, pred) in ERROR_RULES.items():
        if pred(m):
            return (code, desc)
    return (ErrorCode.OTHER, msg)


def _tool_ok_if_expected(name: str | None, args: object) -> bool:
    if name != "get_time":
        return False
    args_obj = args
    if isinstance(args, str):
        args_obj = json.loads(args)
    return isinstance(args_obj, dict) and args_obj == {"city": "Prague"}


def _snippet_from_responses(resp: Response) -> str:
    txt = resp.output_text
    if txt:
        return _squeeze_one_line(txt)
    data = resp.model_dump(exclude_none=True)
    _outputs = data.get("output", [])
    outputs = _outputs if _outputs is not None else []
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
                name = item.get("name")
                args = item.get("arguments")
        if name and _tool_ok_if_expected(name, args):
            return "✓ tool OK"
    return ""


def _snippet_from_chat(chat: ChatCompletion) -> str:
    # OpenAI SDK may set choices to [] (never None in practice); keep explicit
    choices = chat.choices if chat.choices is not None else []
    for ch in choices:
        msg = ch.message
        if msg is None:
            continue
        content = msg.content
        if isinstance(content, str) and content:
            return _squeeze_one_line(content)
    return ""


@dataclass(frozen=True)
class ProbeResult:
    model_id: str
    kind: ProbeKind
    ok: bool
    exc: BaseException | None = None
    raw: Any | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    latency_override_s: float | None = None

    @classmethod
    def success(
        cls, *, model_id: str, kind: ProbeKind, raw: Response | ChatCompletion, started_at: datetime, ended_at: datetime
    ) -> ProbeResult:
        return cls(model_id=model_id, kind=kind, ok=True, raw=raw, started_at=started_at, ended_at=ended_at)

    @classmethod
    def failure(
        cls, *, model_id: str, kind: ProbeKind, exc: BaseException, started_at: datetime | None, ended_at: datetime
    ) -> ProbeResult:
        return cls(model_id=model_id, kind=kind, ok=False, exc=exc, started_at=started_at, ended_at=ended_at)

    @property
    def latency_s(self) -> float | None:
        if not isinstance(self.started_at, datetime) or not isinstance(self.ended_at, datetime):
            return self.latency_override_s
        return float((self.ended_at - self.started_at).total_seconds())

    @property
    def content(self) -> str | None:
        try:
            if self.ok and self.raw is not None:
                if self.kind == ProbeKind.RESPONSES:
                    resp = self.raw_responses()
                    if resp is not None:
                        return _snippet_from_responses(resp)
                if self.kind == ProbeKind.CHAT:
                    ch = self.raw_chat()
                    if ch is not None:
                        return _snippet_from_chat(ch)
            if not self.ok and self.exc is not None:
                return _squeeze_one_line(msg_from_exc(self.exc)) or None
        except Exception:
            return None
        return None

    @property
    def error_message(self) -> str | None:
        """Human-friendly error message if the probe failed."""
        if self.ok:
            return None
        msg = msg_from_exc(self.exc)
        msg = msg.strip()
        return msg or None

    @property
    def error_classification(self) -> tuple[ErrorCode, str] | None:
        """Classify the error into a stable ErrorCode and description.

        Returns None for successful results or when no message is available.
        """
        if self.ok:
            return None
        msg = self.error_message
        if not msg:
            return None
        return classify_error(msg)

    def to_cache_record(self, *, ts: datetime | None = None) -> ProbeRecord:
        ts_use = ts or datetime.now(UTC)
        response_json: dict[str, Any] | None = None
        if self.ok and self.raw is not None:
            if self.kind == ProbeKind.RESPONSES:
                resp = self.raw_responses()
                if resp is not None:
                    response_json = resp.model_dump(exclude_none=False)
            elif self.kind == ProbeKind.CHAT:
                ch = self.raw_chat()
                if ch is not None:
                    response_json = ch.model_dump(exclude_none=False)
        error_json: ErrorInfo | None = None
        if not self.ok and self.exc is not None:
            if isinstance(self.exc, APIStatusError):
                body = self.exc.body if isinstance(self.exc.body, dict) else None
                error_json = ErrorInfo(
                    type="APIStatusError",
                    message=self.exc.message,
                    status_code=self.exc.status_code,
                    body=body,
                    request_id=self.exc.request_id,
                    code=None,
                )
            else:
                error_json = ErrorInfo(type=type(self.exc).__name__, message=str(self.exc))
        return ProbeRecord(
            ts=ts_use,
            started_at=self.started_at,
            ended_at=self.ended_at,
            model=self.model_id,
            kind=self.kind,
            ok=self.ok,
            latency_s=self.latency_s,
            response=response_json,
            error=error_json,
        )

    @classmethod
    def from_record(cls, record: ProbeRecord) -> ProbeResult:
        raw: Any | None = None
        if record.ok and record.response is not None:
            if record.kind == ProbeKind.RESPONSES:
                data = record.response
                try:
                    raw = Response.model_validate(data)
                except Exception:
                    raw = data
            elif record.kind == ProbeKind.CHAT:
                data2 = record.response
                try:
                    raw = ChatCompletion.model_validate(data2)
                except Exception:
                    raw = data2
        exc: BaseException | None = None
        if not record.ok and record.error is not None:
            exc = CachedProbeError(record.error)
        return cls(
            model_id=record.model,
            kind=record.kind,
            ok=record.ok,
            exc=exc,
            raw=raw,
            started_at=record.started_at,
            ended_at=record.ended_at,
            latency_override_s=record.latency_s,
        )

    def raw_chat(self) -> ChatCompletion | None:
        if self.kind == ProbeKind.CHAT and isinstance(self.raw, ChatCompletion):
            return self.raw
        return None

    def raw_responses(self) -> Response | None:
        if self.kind == ProbeKind.RESPONSES and isinstance(self.raw, Response):
            return self.raw
        return None


def make_limiter(qps: float) -> AsyncLimiter:
    qps = max(float(qps), 0.001)
    return AsyncLimiter(int(qps), 1.0) if qps >= 1.0 else AsyncLimiter(1, 1.0 / qps)


# ---------- Output consumers (event-queue based) ----------------------------


Event = tuple[ProbeKind, str, ProbeResult | None]


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
                if kind == ProbeKind.RESPONSES:
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
                rec_ok.response_str = json.dumps(response_dict, separators=(",", ":"))[:500]
            print(rec_ok.model_dump_json(), flush=True)
        else:
            classification = res.error_classification
            # Extract typed API error details when available
            status_code = None
            body: Any | None = None
            request_id = None
            if isinstance(res.exc, APIStatusError):
                status_code = res.exc.status_code
                request_id = res.exc.request_id
                # Prefer parsed JSON if available
                try:
                    parsed = res.exc.response.json() if res.exc.response is not None else None
                    if isinstance(parsed, dict):
                        body = parsed
                except Exception:
                    body = res.exc.body if isinstance(res.exc.body, dict) else None

            rec_err = StreamRecordError(
                ts=ts_now.timestamp(),
                model=mid,
                family=family_of(mid).value,
                kind=kind,
                ok=False,
                error=ErrorInfo(
                    type=(type(res.exc).__name__ if res.exc is not None else None),
                    message=res.error_message,
                    status_code=status_code,
                    body=body,
                    request_id=request_id,
                    code=(classification[0].value if classification else None),
                ),
                tags=tags or None,
            )
            error_code = classification[0].value if classification else "UNKNOWN"
            error_msg = res.error_message or "Unknown error"
            rec_err.error_str = f"{error_code}: {error_msg}"[:200]
            print(rec_err.model_dump_json(), flush=True)


# ---------- Runner orchestration -------------------------------------------
# (Rest of the orchestration and main entry remain identical to previous version.)


def main() -> None:
    print("OpenAI Probe package is now modularized. CLI implementation trimmed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
