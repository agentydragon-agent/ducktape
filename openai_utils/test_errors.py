"""Unit tests for openai_utils.errors."""

from __future__ import annotations

import json

import httpx
import openai
import pytest
import pytest_bazel
from openai import BadRequestError

from openai_utils.model import BoundOpenAIModel, ResponsesRequest
from openai_utils.retry import RetryingOpenAIModel


def _error_transport(code: str, message: str) -> httpx.MockTransport:
    """Transport returning a 400 with an OpenAI-shaped error body."""
    body = json.dumps({"error": {"message": message, "type": "invalid_request_error", "code": code}})
    return httpx.MockTransport(
        lambda _request: httpx.Response(400, content=body, headers={"content-type": "application/json"})
    )


async def test_non_context_length_bad_request_propagates() -> None:
    """A BadRequestError with a non-context-length code propagates unchanged."""
    transport = _error_transport("invalid_request_error", "invalid request")
    inner = openai.AsyncOpenAI(api_key="test-key", http_client=httpx.AsyncClient(transport=transport))
    client = RetryingOpenAIModel(base=BoundOpenAIModel(client=inner, model="test"))

    with pytest.raises(BadRequestError):
        await client.responses_create(ResponsesRequest(input="hi", max_output_tokens=16))


if __name__ == "__main__":
    pytest_bazel.main()
