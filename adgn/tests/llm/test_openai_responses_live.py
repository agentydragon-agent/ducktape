import os
from typing import Any, cast

import openai
from openai.types.responses import EasyInputMessageParam, ResponseInputParam
import pytest


@pytest.mark.live_llm
async def test_responses_nonstreaming_live(tmp_path):
    """Live test: call OpenAI Responses.create (non-streaming).

    Requires OPENAI_API_KEY in the environment. Uses OPENAI_MODEL if set or
    falls back to 'o4-mini'. This test is explicitly marked `live_llm` and is
    excluded by default in CI runs.
    """
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set; skipping live test")

    client = openai.AsyncOpenAI()
    model = os.getenv("OPENAI_MODEL", "o4-mini")

    # Use TypedDict (input type) directly
    inp: list[EasyInputMessageParam] = [
        {"type": "message", "role": "user", "content": "Say hello in one short sentence."}
    ]

    # Non-streaming call
    resp = await client.responses.create(model=model, input=cast(ResponseInputParam, inp))

    # Try to normalize to dict for assertions
    data: dict[str, Any] | None
    try:
        data = resp.model_dump(exclude_none=True)
    except Exception:
        # If model_dump not present, assume dict-like
        data = resp if isinstance(resp, dict) else None

    assert data is not None, "Response payload missing"
    # Expect an 'id' or 'object' token from Responses API
    assert ("id" in data) or (data.get("object") is not None)


@pytest.mark.live_llm
async def test_responses_streaming_live(tmp_path):
    """Live test: call OpenAI Responses.create with stream=True and iterate.

    Requires OPENAI_API_KEY in the environment. The test collects streamed
    events and asserts that at least one event was received.
    """
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set; skipping live test")

    client = openai.AsyncOpenAI()
    model = os.getenv("OPENAI_MODEL", "o4-mini")

    # Use TypedDict (input type) directly
    inp: list[EasyInputMessageParam] = [
        {"type": "message", "role": "user", "content": "Stream: say numbers 1..3 as separate events"}
    ]

    # AsyncOpenAI with stream=True returns an async iterator
    stream = await client.responses.create(model=model, input=cast(ResponseInputParam, inp), stream=True)

    got_any = False
    items: list[dict[str, Any] | None] = []
    async for event in stream:
        got_any = True
        try:
            items.append(event.model_dump(exclude_none=True))
        except Exception:
            items.append(event if isinstance(event, dict) else None)

    assert got_any, "No stream events received"
    assert any(it is not None for it in items), "Stream events contained no usable payload"
