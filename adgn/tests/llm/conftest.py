from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
import os
from pathlib import Path
from typing import Any

import openai as _openai
from openai import AsyncOpenAI
from openai.types.responses import Response, ResponseOutputMessage, ResponseOutputText
from openai.types.responses.response_usage import (
    InputTokensDetails,
    OutputTokensDetails,
    ResponseUsage,
)
import pytest

from .support.openai_mock import LIVE, OpenAIClient, make_mock


# Ensure MiniCodex logs go to a temp dir in tests
@pytest.fixture(autouse=True)
def _mini_codex_logdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log_dir = tmp_path / "mini_codex_logs"
    monkeypatch.setenv("MINICODEX_LOG_DIR", str(log_dir))


# --- Minimal helpers/fixtures for building OpenAI Responses and fake client ---


def _make_usage(input_tokens: int = 0, output_tokens: int = 0) -> ResponseUsage:
    return ResponseUsage(
        input_tokens=input_tokens,
        input_tokens_details=InputTokensDetails(cached_tokens=0),
        output_tokens=output_tokens,
        output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
        total_tokens=input_tokens + output_tokens,
    )


def make_assistant_text_response(*, model: str, text: str) -> Response:
    msg = ResponseOutputMessage(
        id="msg1",
        type="message",
        role="assistant",
        status="completed",
        content=[ResponseOutputText(type="output_text", text=text, annotations=[])],
    )
    return Response(
        id="resp_msg",
        created_at=1,
        model=model,
        object="response",
        output=[msg],
        parallel_tool_calls=False,
        tool_choice="auto",
        tools=[],
        usage=_make_usage(0, max(1, len(text))),
    )


class _FakeResponsesSequence:
    """Async stub for client.responses that returns a predefined sequence of Response objects."""

    def __init__(self, outputs: Iterable[Response]) -> None:
        self._outputs: list[Response] = list(outputs)
        self.calls = 0

    async def create(self, **kwargs: Any) -> Response:  # type: ignore[override]
        idx = min(self.calls, len(self._outputs) - 1)
        self.calls += 1
        return self._outputs[idx]


class FakeOpenAIClient:
    def __init__(self, outputs: Iterable[Response]) -> None:
        self.responses = _FakeResponsesSequence(outputs)


@pytest.fixture
def assistant_response_factory() -> Callable[[str, str], Response]:
    def _make(model: str, text: str) -> Response:
        return make_assistant_text_response(model=model, text=text)

    return _make


@pytest.fixture
def fake_openai_client_factory() -> Callable[[Iterable[Response]], FakeOpenAIClient]:
    def _make(outputs: Iterable[Response]) -> FakeOpenAIClient:
        return FakeOpenAIClient(outputs)

    return _make


# --- Opt-in OpenAI client policy for tests ---
# By default, tests should NOT create real AsyncOpenAI() instances. Replace the
# constructor with a raising stub so tests must explicitly opt-in via the
# `openai_client` fixture when they need a real (or mocked) AsyncOpenAI instance.

_orig_async = getattr(_openai, "AsyncOpenAI", None)


def _raising_async(*args, **kwargs):
    raise RuntimeError(
        "AsyncOpenAI() is disabled by default for tests.\n"
        "If a test needs an OpenAI client, request the `openai_client` fixture or add an explicit patch.\n"
        "This ensures tests explicitly opt-in to using live/mocked clients and avoid accidental network calls.",
    )


@pytest.fixture(autouse=True)
def fail_openai_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Autouse fixture that replaces openai.AsyncOpenAI with a raising stub.

    Tests that need access must explicitly use the `openai_client` fixture which
    temporarily restores the real AsyncOpenAI constructor for that test.
    """
    monkeypatch.setattr(_openai, "AsyncOpenAI", _raising_async)


@pytest.fixture
async def openai_client(monkeypatch: pytest.MonkeyPatch):
    """Opt-in fixture: restore the real AsyncOpenAI for the duration of the test and yield an instance.

    Usage:
        async def test_x(openai_client):
            resp = await openai_client.responses.create(...)
    """
    if _orig_async is None:
        raise RuntimeError(
            "No openai.AsyncOpenAI available in this environment to restore",
        )

    # restore the original constructor for this test
    monkeypatch.setattr(_openai, "AsyncOpenAI", _orig_async)
    client = _orig_async()
    try:
        yield client
    finally:
        # cleanup client if it supports aclose()
        try:
            aclose = getattr(client, "aclose", None)
            if aclose is not None:
                await aclose()
        finally:
            # ensure we put back the raising stub
            monkeypatch.setattr(_openai, "AsyncOpenAI", _raising_async)


# --- Minimal, function-shaped mock for responses.create ---
# Tests can parametrize a single async function shaped like client.responses.create
# and receive a client whose `responses.create(**kwargs)` forwards to that function.

ResponsesCreateFn = Callable[..., Awaitable[Any]]


@pytest.fixture
def responses_create_fn(
    request,
) -> ResponsesCreateFn:  # provided via indirect parametrize
    return request.param  # type: ignore[no-any-return]


@pytest.fixture
def openai_client_mock(responses_create_fn: ResponsesCreateFn):
    class _Responses:
        async def create(self, **kwargs: Any) -> Any:  # mirror SDK surface
            return await responses_create_fn(**kwargs)

    class _Client:
        def __init__(self) -> None:
            self.responses = _Responses()

    return _Client()


# Live AsyncOpenAI for tests that opt into LIVE sentinel
@pytest.fixture(scope="session")
def live_openai() -> AsyncOpenAI:
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")
    return AsyncOpenAI()


# --- Single-param OpenAI fixture (mock OR live via sentinel) ---
# Usage in tests:
#   @pytest.mark.parametrize(
#       "openai_client_param",
#       [pytest.param(behavior_fn, id="mock"), pytest.param("live", id="live", marks=pytest.mark.live_llm)],
#       indirect=True,
#   )
#   async def test_shared(openai_client_param):
#       ...


@pytest.fixture
def openai_client_param(
    request, live_openai
) -> OpenAIClient:  # provided via indirect parametrize
    val = request.param
    if callable(val):  # behavior function → mock
        return make_mock(val)
    if val is LIVE:
        return live_openai
    raise TypeError("openai_client_param must be a behavior fn or LIVE")
