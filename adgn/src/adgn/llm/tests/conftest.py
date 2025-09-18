from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from openai.types.responses import Response, ResponseOutputMessage, ResponseOutputText
from openai.types.responses.response_usage import (
    InputTokensDetails,
    OutputTokensDetails,
    ResponseUsage,
)
import pytest


# Ensure MiniCodex logs go to a temp dir in tests
@pytest.fixture(autouse=True)
def _mini_codex_logdir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
