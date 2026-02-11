from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from adgn.openai_utils.model import OpenAIModelProto, ResponsesRequest, ResponsesResult

# Sentinel for selecting a real AsyncOpenAI client in parameterized tests
LIVE = object()

# Function type for a mocked OpenAI Responses API call (our Pydantic request/response)
ResponsesCreateFn = Callable[[ResponsesRequest], Awaitable[ResponsesResult]]


class CapturingOpenAIModel(OpenAIModelProto):
    """Wrapper that captures all requests to an underlying OpenAI model.

    Wraps any OpenAIModelProto and records all requests in the .captured list.
    Explicitly implements OpenAIModelProto by delegating to the inner model.
    """

    def __init__(self, inner: OpenAIModelProto) -> None:
        self._inner = inner
        self.captured: list[ResponsesRequest] = []

    @property
    def model(self) -> str:
        return self._inner.model

    async def responses_create(self, req: ResponsesRequest) -> ResponsesResult:
        self.captured.append(req.model_copy(deep=True))
        return await self._inner.responses_create(req)


class CapturedRequest(BaseModel):
    """Pydantic wrapper for captured Responses.create kwargs used in tests.

    Exposes `.input` as a first-class attribute and preserves unknown fields.
    """

    input: list[dict[str, Any]] | None = None
    model_config = ConfigDict(extra="allow")


class FakeOpenAIModel:
    """Mock OpenAI model that returns predefined responses.

    This is a basic mock implementation of OpenAIModelProto.
    Wrap with CapturingOpenAIModel if you need to inspect requests.
    """

    def __init__(self, outputs: list[ResponsesResult] | tuple[ResponsesResult, ...]) -> None:
        self._outputs: list[ResponsesResult] = list(outputs)
        self.calls = 0

    @property
    def model(self) -> str:
        return "fake-model"

    async def responses_create(self, req: ResponsesRequest) -> ResponsesResult:
        if not isinstance(req, ResponsesRequest):
            raise TypeError("responses_create expects a ResponsesRequest instance")
        idx = min(self.calls, len(self._outputs) - 1) if self._outputs else 0
        self.calls += 1
        return self._outputs[idx]


class OpenAIClient(Protocol):
    @property
    def responses(self) -> Any: ...  # pragma: no cover


def make_mock(responses_create_fn: ResponsesCreateFn) -> CapturingOpenAIModel:
    """Construct a capturing mock client that delegates to the provided behavior.

    The returned client has a .captured attribute that records all requests.
    """

    class _MockClient:
        """Mock OpenAI client that delegates responses_create to provided function."""

        @property
        def model(self) -> str:
            return "test-model"

        async def responses_create(self, req: ResponsesRequest) -> ResponsesResult:
            return await responses_create_fn(req)

    # Wrap the mock with CapturingOpenAIModel to add request recording
    return CapturingOpenAIModel(_MockClient())
