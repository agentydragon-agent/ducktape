from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from openai.types.responses.response_create_params import (
    ResponseCreateParamsNonStreaming,
)

# Sentinel for selecting a real AsyncOpenAI client in parameterized tests
LIVE = object()

# Function type for a mocked OpenAI Responses API call (typed request object)
ResponsesCreateFn = Callable[[ResponseCreateParamsNonStreaming], Awaitable[Any]]


class OpenAIClient(Protocol):
    async def responses_create(self, **kwargs: Any) -> Any: ...  # pragma: no cover


def make_mock(responses_create_fn: ResponsesCreateFn) -> OpenAIClient:
    """Construct a minimal mock client whose `responses.create(**kwargs)`
    forwards to the provided async behavior function.
    """

    class _Responses:
        async def create(self, **kwargs: Any) -> Any:  # mirror SDK surface
            req = ResponseCreateParamsNonStreaming(**kwargs)
            return await responses_create_fn(req)

    class _Client:
        def __init__(self) -> None:
            self.responses = _Responses()

        # Convenience for codepaths that call a flattened method
        async def responses_create(self, **kwargs: Any) -> Any:
            return await self.responses.create(**kwargs)

    return _Client()
