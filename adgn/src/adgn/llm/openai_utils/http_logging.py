"""OpenAI client wrappers with verbatim HTTP logging (masked auth).

This module provides small helpers to construct OpenAI/AsyncOpenAI clients
that log raw HTTP requests/responses to a JSONL file for diagnostics.

Notes
- Authorization header is masked (***).
- Bodies are logged as UTF-8 text with errors="ignore" to avoid crashes on
  binary content.
- Log format: one JSON object per line with keys {kind, ...} where kind is
  "request" or "response".

Typical usage

from pathlib import Path
from adgn.llm.openai_http_logging import make_logged_async_openai

client = make_logged_async_openai(Path("./openai_http.jsonl"))
# pass `client` where an AsyncOpenAI is expected

"""

from __future__ import annotations

import json
from functools import partial
from pathlib import Path
from typing import Any

import httpx
from openai import AsyncOpenAI, OpenAI


async def _log_write(path: Path, record: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        # Best-effort logging; never crash the caller
        pass


async def _on_request(
    req: httpx.Request, *, path: Path
) -> None:  # pragma: no cover - HTTP hook
    headers = {
        k: ("***" if k.lower() == "authorization" else v)
        for k, v in req.headers.items()
    }
    try:
        body = getattr(req, "content", b"") or b""
    except Exception:
        body = b""
    await _log_write(
        path,
        {
            "kind": "request",
            "method": req.method,
            "url": str(req.url),
            "headers": headers,
            "body": body.decode("utf-8", errors="ignore"),
        },
    )


async def _on_response(
    resp: httpx.Response, *, path: Path
) -> None:  # pragma: no cover - HTTP hook
    req = resp.request
    headers = {
        k: ("***" if k.lower() == "authorization" else v)
        for k, v in req.headers.items()
    }
    try:
        req_body = getattr(req, "content", b"") or b""
    except Exception:
        req_body = b""
    # Safely read response body for streaming responses
    resp_body_bytes: bytes = b""
    try:
        resp_body_bytes = await resp.aread()
    except Exception:
        try:
            resp_body_bytes = resp.content
        except Exception:
            resp_body_bytes = b""
    await _log_write(
        path,
        {
            "kind": "response",
            "status": resp.status_code,
            "req_url": str(req.url),
            "req_headers": headers,
            "req_body": req_body.decode("utf-8", errors="ignore"),
            "resp_headers": dict(resp.headers),
            "resp_body": resp_body_bytes.decode("utf-8", errors="ignore"),
        },
    )


def make_logged_async_openai(log_path: Path | str) -> AsyncOpenAI:
    """Create an AsyncOpenAI client that logs raw HTTP traffic to log_path.

    The returned client owns an httpx.AsyncClient with event hooks installed.
    The caller is responsible for closing the OpenAI client when done.
    """
    p = Path(log_path)
    http = httpx.AsyncClient(
        event_hooks={
            "request": [partial(_on_request, path=p)],
            "response": [partial(_on_response, path=p)],
        }
    )
    return AsyncOpenAI(http_client=http)


def make_logged_openai(log_path: Path | str) -> OpenAI:
    """Create a sync OpenAI client that logs raw HTTP traffic to log_path.

    Note: This uses httpx.Client underneath; prefer the async variant in new code.
    """
    p = Path(log_path)

    def _on_req(req: httpx.Request):  # pragma: no cover - HTTP hook
        return httpx.run(_on_request(req, path=p))  # type: ignore[attr-defined]

    def _on_resp(resp: httpx.Response):  # pragma: no cover - HTTP hook
        return httpx.run(_on_response(resp, path=p))  # type: ignore[attr-defined]

    http = httpx.Client(
        event_hooks={
            "request": [_on_req],
            "response": [_on_resp],
        }
    )
    return OpenAI(http_client=http)
