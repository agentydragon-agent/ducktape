from __future__ import annotations

import json
import os
from typing import Any, Callable, Iterable

import pytest
from openai.types.responses import (
    Response,
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)
from openai.types.responses.response_reasoning_item import ResponseReasoningItem
from openai.types.responses.response_reasoning_item import Summary as ReasoningSummary
from openai.types.responses.response_usage import (
    InputTokensDetails,
    OutputTokensDetails,
    ResponseUsage,
)

# --- Lightweight helpers for building SDK-shaped Responses ---


def _make_usage(input_tokens: int = 0, output_tokens: int = 0) -> ResponseUsage:
    return ResponseUsage(
        input_tokens=input_tokens,
        input_tokens_details=InputTokensDetails(cached_tokens=0),
        output_tokens=output_tokens,
        output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
        total_tokens=input_tokens + output_tokens,
    )


def make_tool_call_response(*, model: str, call_id: str, name: str, arguments: dict[str, Any] | str) -> Response:
    args_str = json.dumps(arguments) if isinstance(arguments, dict) else str(arguments)
    tc = ResponseFunctionToolCall(type="function_call", call_id=call_id, name=name, arguments=args_str)
    return Response(
        id="resp_tc",
        created_at=0,
        model=model,
        object="response",
        output=[tc],
        parallel_tool_calls=False,
        tool_choice="auto",
        tools=[],
        usage=_make_usage(0, 0),
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


class FakeResponsesSequence:
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
        self.responses = FakeResponsesSequence(outputs)


# --- Pytest fixtures (prefer fixtures over cross-importing test modules) ---


@pytest.fixture
def assistant_response_factory() -> Callable[[str, str], Response]:
    def _make(model: str, text: str) -> Response:
        return make_assistant_text_response(model=model, text=text)

    return _make


# Shared model fixture for live tests that need a reasoning-capable model
@pytest.fixture(scope="session")
def reasoning_model() -> str:
    # Default to gpt-5-nano for fast, reasoning-capable behavior; allow override via env
    return os.environ.get("RESPONSES_TEST_MODEL", "gpt-5-nano")


@pytest.fixture
def tool_call_response_factory() -> Callable[[str, str, str, dict[str, Any] | str], Response]:
    def _make(model: str, call_id: str, name: str, arguments: dict[str, Any] | str) -> Response:
        return make_tool_call_response(model=model, call_id=call_id, name=name, arguments=arguments)

    return _make


@pytest.fixture
def fake_openai_client_factory(
    responses_factory,
) -> Callable[[Iterable[Response]], FakeOpenAIClient]:
    """Function-scoped factory that returns a FakeOpenAIClient built from a sequence of
    SDK Response objects using the session-scoped responses_factory.
    """

    def _make(outputs: Iterable[Response]) -> FakeOpenAIClient:
        return responses_factory.make_fake_client(outputs)

    return _make


# Convenience factory that bundles a model and helpers for creating SDK Responses
class ResponsesFactory:
    def __init__(self, model: str):
        self.model = model

    def make_tool_call_response(self, call_id: str, name: str, arguments: dict[str, Any] | str) -> Response:
        return make_tool_call_response(model=self.model, call_id=call_id, name=name, arguments=arguments)

    def make_assistant_text_response(self, text: str) -> Response:
        return make_assistant_text_response(model=self.model, text=text)

    def make_reasoning_then_tool(self, call_id: str, name: str, arguments: dict[str, Any]) -> Response:
        # Build a Response that contains a reasoning item followed by a function_call
        return Response(
            id="resp_1",
            created_at=0,
            model=self.model,
            object="response",
            output=[
                ResponseReasoningItem(
                    id="rs_1",
                    type="reasoning",
                    summary=[ReasoningSummary(type="summary_text", text="thinking...")],
                ),
                ResponseFunctionToolCall(
                    type="function_call",
                    call_id=call_id,
                    name=name,
                    arguments=json.dumps(arguments),
                ),
            ],
            parallel_tool_calls=False,
            tool_choice="auto",
            tools=[],
            usage=ResponseUsage(
                input_tokens=0,
                input_tokens_details=InputTokensDetails(cached_tokens=0),
                output_tokens=0,
                output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
                total_tokens=0,
            ),
        )

    def make_final_assistant(self, text: str) -> Response:
        msg = ResponseOutputMessage(
            id="m1",
            type="message",
            role="assistant",
            status="completed",
            content=[ResponseOutputText(type="output_text", text=text, annotations=[])],
        )
        return Response(
            id="resp_2",
            created_at=1,
            model=self.model,
            object="response",
            output=[msg],
            parallel_tool_calls=False,
            tool_choice="auto",
            tools=[],
            usage=ResponseUsage(
                input_tokens=0,
                input_tokens_details=InputTokensDetails(cached_tokens=0),
                output_tokens=max(1, len(text)),
                output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
                total_tokens=max(1, len(text)),
            ),
        )

    def make_fake_client(self, seq: Iterable[Response]) -> FakeOpenAIClient:
        return FakeOpenAIClient(seq)


@pytest.fixture(scope="session")
def responses_factory(reasoning_model: str) -> ResponsesFactory:
    """Provide a small factory bound to a reasoning-capable model for tests.

    Usage in tests:
      def test_x(responses_factory):
          r = responses_factory.make_tool_call_response(...)
          client = responses_factory.make_fake_client([r, ...])
    """
    return ResponsesFactory(reasoning_model)
