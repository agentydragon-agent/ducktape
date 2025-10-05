from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from adgn.openai_utils.model import (
    OpenAIModelProto,
    ResponsesRequest,
    ResponsesResult,
)

# Sentinel for selecting a real AsyncOpenAI client in parameterized tests
LIVE = object()

# Function type for a mocked OpenAI Responses API call (our Pydantic request/response)
ResponsesCreateFn = Callable[[ResponsesRequest], Awaitable[ResponsesResult]]


class CapturedRequest(BaseModel):
    """Pydantic wrapper for captured Responses.create kwargs used in tests.

    Exposes `.input` as a first-class attribute and preserves unknown fields.
    """

    input: list[dict[str, Any]] | None = None
    model_config = ConfigDict(extra="allow")


class _CapturingResponses:
    """Pydantic-only stub that returns a predefined sequence and records calls.

    - calls: number of create() invocations
    - captured: list of ResponsesRequest objects
    """

    def __init__(self, outputs: Iterable[ResponsesResult]) -> None:
        self._outputs: list[ResponsesResult] = list(outputs)
        self.calls = 0
        self.captured: list[ResponsesRequest] = []

    async def create(self, req: ResponsesRequest) -> ResponsesResult:
        self.captured.append(req.model_copy(deep=True))
        idx = min(self.calls, len(self._outputs) - 1) if self._outputs else 0
        self.calls += 1
        return self._outputs[idx]


class CapturingClient(OpenAIModelProto):
    """Shared test helper exposing a minimal responses.create stub for captures.

    Provides .responses with a create(**kwargs) method that records typed
    ResponseCreateParamsNonStreaming requests under .captured and returns a
    predefined sequence of Response-like outputs.
    """

    def __init__(self, outputs: Iterable[Any]) -> None:
        self.responses = _CapturingResponses(outputs)

    async def responses_create(self, req: ResponsesRequest) -> ResponsesResult:
        return await self.responses.create(req)


class OpenAIClient(Protocol):
    @property
    def responses(self) -> Any: ...  # pragma: no cover


def make_mock(responses_create_fn: ResponsesCreateFn) -> OpenAIClient:
    """Construct a minimal mock client whose responses.create(req) calls the provided behavior."""

    class _Responses:
        async def create(self, req: ResponsesRequest) -> ResponsesResult:
            return await responses_create_fn(req)

    class _Client(OpenAIModelProto):
        def __init__(self) -> None:
            self.responses = _Responses()

        async def responses_create(self, req: ResponsesRequest) -> ResponsesResult:
            return await self.responses.create(req)

    return _Client()
