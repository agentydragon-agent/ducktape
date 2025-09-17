from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import httpx
import openai
from openai import AsyncOpenAI
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

# Default retry policy: 5 attempts, exponential backoff with jitter (~0.5s..60s)
_DEFAULT_ATTEMPTS = 10
_DEFAULT_INITIAL = 0.5
_DEFAULT_MAX = 60.0
_RETRY_ON: Iterable[type[BaseException]] = (
    openai.RateLimitError,
    openai.APIConnectionError,
    openai.InternalServerError,
    openai.APITimeoutError,
    httpx.TimeoutException,
    httpx.ConnectError,
)


def retry_decorator(
    attempts: int = _DEFAULT_ATTEMPTS,
    initial: float = _DEFAULT_INITIAL,
    maximum: float = _DEFAULT_MAX,
    retry_exceptions: Iterable[type[BaseException]] = _RETRY_ON,
):
    """Return a tenacity.retry decorator with our standard settings.

    Example:
        @retry_decorator()
        async def fn(...):
            ...
    """
    return retry(
        stop=stop_after_attempt(attempts),
        wait=wait_exponential_jitter(initial=initial, max=maximum),
        retry=retry_if_exception_type(tuple(retry_exceptions)),
    )


@retry_decorator()
async def responses_create_with_retries(client: AsyncOpenAI, **kwargs: Any) -> Any:
    return await client.responses.create(**kwargs)


@retry_decorator()
async def chat_create_with_retries(client: AsyncOpenAI, **kwargs: Any) -> Any:
    # kwargs should contain: messages=..., model=..., etc.
    return await client.chat.completions.create(**kwargs)
