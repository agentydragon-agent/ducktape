"""Factories for provider-agnostic LLM clients used across entrypoints.

Goals
- Single-ish construction point for OpenAI-backed clients used by CLIs/services
- Optional HTTP logging via a small wrapper (single JSONL per process/run)
- Return the provider-agnostic interface `ResponsesClient` consumed by agents

Environment knobs
- ADGN_OPENAI_HTTP_LOG: if set to a filepath, enable raw HTTP logging there
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Tuple

from openai import AsyncOpenAI

from adgn.llm.openai_utils.model import (
    BoundOpenAIModel,
    RetryingOpenAIModel,
    OpenAIModelProto,
)
from adgn.llm.openai_utils.http_logging import make_logged_async_openai


_ASYNC_CLIENTS: Dict[Tuple[str | None], AsyncOpenAI] = {}


def _get_async_openai(*, log_path: Path | str | None = None) -> AsyncOpenAI:
    """Return a cached AsyncOpenAI client (optionally with HTTP logging).

    Cache key is the logging path (None vs specific path). This ensures we avoid
    constructing many clients per process while still allowing an opt-in logging
    variant when explicitly requested.
    """
    key: Tuple[str | None] = (str(log_path) if log_path else None,)
    if key in _ASYNC_CLIENTS:
        return _ASYNC_CLIENTS[key]
    if log_path:
        client = make_logged_async_openai(Path(log_path))
    else:
        client = AsyncOpenAI()
    _ASYNC_CLIENTS[key] = client
    return client


def get_async_openai(log_http_path: Path | str | None = None) -> AsyncOpenAI:
    """Public helper to obtain a shared AsyncOpenAI client (optionally with HTTP logging)."""
    return _get_async_openai(log_path=log_http_path)


def build_client(
    model: str,
    *,
    log_http_path: Path | str | None = None,
) -> OpenAIModelProto:
    """Create a typed, retrying Responses client for the given model.

    - Respects ADGN_OPENAI_HTTP_LOG if log_http_path is not provided
    """
    if log_http_path is None:
        env_path = os.environ.get("ADGN_OPENAI_HTTP_LOG")
        log_http_path = Path(env_path) if env_path else None
    inner = _get_async_openai(log_path=log_http_path)
    base = BoundOpenAIModel(client=inner, model=model)
    return RetryingOpenAIModel(base=base)
