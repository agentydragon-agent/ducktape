"""Dual mock/live tests for OpenAI API error translation and smoke tests.

Mock tests use httpx.MockTransport to return canned HTTP responses, letting
the OpenAI SDK parse error bodies the same way it would from real servers.
Live tests hit the real OpenAI API to confirm end-to-end behavior.
"""

from __future__ import annotations

import json
import os
from typing import Any, cast

import httpx
import openai
import pytest
import pytest_bazel
from openai.types.responses import EasyInputMessageParam, ResponseInputParam

from openai_utils.client_factory import build_client
from openai_utils.errors import ContextLengthExceededError
from openai_utils.model import BoundOpenAIModel, OpenAIModelProto, ResponsesRequest
from openai_utils.retry import RetryingOpenAIModel, chat_create_with_retries

# --- Helpers ---


def _error_transport(code: str, message: str) -> httpx.MockTransport:
    """Transport returning a 400 with an OpenAI-shaped error body."""
    body = json.dumps({"error": {"message": message, "type": "invalid_request_error", "code": code}})
    return httpx.MockTransport(
        lambda _request: httpx.Response(400, content=body, headers={"content-type": "application/json"})
    )


def _mock_client(transport: httpx.MockTransport) -> OpenAIModelProto:
    """Build the same client stack as build_client(), but backed by a mock transport."""
    inner = openai.AsyncOpenAI(api_key="test-key", http_client=httpx.AsyncClient(transport=transport))
    return RetryingOpenAIModel(base=BoundOpenAIModel(client=inner, model="test"))


async def _assert_context_length_exceeded(client: OpenAIModelProto, req: ResponsesRequest) -> None:
    """Shared assertion: responses_create raises ContextLengthExceededError."""
    with pytest.raises(ContextLengthExceededError):
        await client.responses_create(req)


def _huge_prompt(length: int = 5_000_000) -> str:
    """5M chars is ~1.25M tokens, exceeding even the largest context windows."""
    return "x" * length


# --- Mock tests (no network, no API key) ---


async def test_context_length_exceeded_mock() -> None:
    """Mock: SDK parses context_length_exceeded → ContextLengthExceededError."""
    client = _mock_client(_error_transport("context_length_exceeded", "context length exceeded"))
    await _assert_context_length_exceeded(client, ResponsesRequest(input="hi", max_output_tokens=16))


# --- Live tests (require OPENAI_API_KEY) ---


@pytest.mark.live_openai_api
async def test_context_length_exceeded_live(require_openai_api_key, live_openai_model) -> None:
    """Live: oversized prompt → ContextLengthExceededError."""
    client = build_client(live_openai_model)
    await _assert_context_length_exceeded(client, ResponsesRequest(input=_huge_prompt(), max_output_tokens=16))


@pytest.mark.live_openai_api
async def test_responses_nonstreaming_live(tmp_path):
    """Live-only: non-streaming Responses.create returns a response."""
    client = openai.AsyncOpenAI()
    model = os.getenv("OPENAI_MODEL", "o4-mini")

    inp: list[EasyInputMessageParam] = [
        {"type": "message", "role": "user", "content": "Say hello in one short sentence."}
    ]

    resp = await client.responses.create(model=model, input=cast(ResponseInputParam, inp))

    data = resp.model_dump(exclude_none=True)
    assert ("id" in data) or (data.get("object") is not None)


@pytest.mark.live_openai_api
async def test_responses_streaming_live(tmp_path):
    """Live-only: streaming Responses.create produces events."""
    client = openai.AsyncOpenAI()
    model = os.getenv("OPENAI_MODEL", "o4-mini")

    inp: list[EasyInputMessageParam] = [
        {"type": "message", "role": "user", "content": "Stream: say numbers 1..3 as separate events"}
    ]

    stream = await client.responses.create(model=model, input=cast(ResponseInputParam, inp), stream=True)

    items: list[dict[str, Any]] = []
    async for event in stream:
        items.append(event.model_dump(exclude_none=True))

    assert items, "No stream events received"


@pytest.mark.live_openai_api
async def test_chat_context_length_exceeded_live(require_openai_api_key, live_openai_model, live_async_openai) -> None:
    """Live-only: Chat Completions API context length → ContextLengthExceededError."""
    params = {"model": live_openai_model, "messages": [{"role": "user", "content": _huge_prompt()}], "max_tokens": 8}

    with pytest.raises(ContextLengthExceededError):
        await chat_create_with_retries(live_async_openai, params)


if __name__ == "__main__":
    pytest_bazel.main()
