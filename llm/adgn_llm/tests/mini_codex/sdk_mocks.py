from __future__ import annotations

import json
from typing import Any, Iterable

from openai.types.responses import (
    Response,
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)
from openai.types.responses.response_usage import (
    InputTokensDetails,
    OutputTokensDetails,
    ResponseUsage,
)


def make_usage(input_tokens: int = 0, output_tokens: int = 0) -> ResponseUsage:
    return ResponseUsage(
        input_tokens=input_tokens,
        input_tokens_details=InputTokensDetails(cached_tokens=0),
        output_tokens=output_tokens,
        output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
        total_tokens=input_tokens + output_tokens,
    )


def make_tool_call_response(*, model: str, call_id: str, name: str, arguments: dict[str, Any] | str) -> Response:
    args_str = json.dumps(arguments) if isinstance(arguments, dict) else str(arguments)
    tc = ResponseFunctionToolCall(
        type="function_call",
        call_id=call_id,
        name=name,
        arguments=args_str,
    )
    return Response(
        id="resp_tc",
        created_at=0,
        model=model,
        object="response",
        output=[tc],
        parallel_tool_calls=False,
        tool_choice="auto",
        tools=[],
        usage=make_usage(0, 0),
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
        usage=make_usage(0, max(1, len(text))),
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
    def __init__(self, responses: Iterable[Response]) -> None:
        self.responses = FakeResponsesSequence(responses)
