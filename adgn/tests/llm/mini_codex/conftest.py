from __future__ import annotations

from collections.abc import Callable, Iterable
import json
import os
import uuid
from typing import Any

from openai.types.responses import (
    Response,
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)
from openai.types.responses.response_reasoning_item import (
    ResponseReasoningItem,
    Summary as ReasoningSummary,
)
from openai.types.responses.response_usage import (
    InputTokensDetails,
    OutputTokensDetails,
    ResponseUsage,
)
import pytest

from adgn.llm.mini_codex.mcp_manager import McpManager
from adgn.llm.mcp._shared.container_session import ContainerOptions
from adgn.llm.mcp.docker_exec.server import make_container_exec_mcp
from adgn.llm.mcp.inproc_transport import make_inproc_slot_spec

# --- Lightweight helpers for building SDK-shaped Responses ---


def _make_usage(input_tokens: int = 0, output_tokens: int = 0) -> ResponseUsage:
    return ResponseUsage(
        input_tokens=input_tokens,
        input_tokens_details=InputTokensDetails(cached_tokens=0),
        output_tokens=output_tokens,
        output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
        total_tokens=input_tokens + output_tokens,
    )


def make_tool_call_response(
    *,
    model: str,
    call_id: str,
    name: str,
    arguments: dict[str, Any] | str,
) -> Response:
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
        usage=_make_usage(0, 0),
    )


def make_assistant_text_response(*, model: str, text: str) -> Response:
    msg = ResponseOutputMessage(
        id=f"msg_{uuid.uuid4().hex[:8]}",
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
def tool_call_response_factory() -> Callable[
    [str, str, str, dict[str, Any] | str],
    Response,
]:
    def _make(
        model: str,
        call_id: str,
        name: str,
        arguments: dict[str, Any] | str,
    ) -> Response:
        return make_tool_call_response(
            model=model,
            call_id=call_id,
            name=name,
            arguments=arguments,
        )

    return _make


# Convenience factory that bundles a model and helpers for creating SDK Responses
class ResponsesFactory:
    def __init__(self, model: str):
        self.model = model
        self._counter = 0

    def _next_id(self) -> int:
        self._counter += 1
        return self._counter

    def make_tool_call_response(
        self,
        call_id: str,
        name: str,
        arguments: dict[str, Any] | str,
    ) -> Response:
        return make_tool_call_response(
            model=self.model,
            call_id=call_id,
            name=name,
            arguments=arguments,
        )

    def make_assistant_text_response(self, text: str) -> Response:
        return make_assistant_text_response(model=self.model, text=text)

    def make_reasoning_then_tool(
        self,
        call_id: str,
        name: str,
        arguments: dict[str, Any],
    ) -> Response:
        # Build a Response that contains a reasoning item followed by a function_call
        return Response(
            id="resp_1",
            created_at=0,
            model=self.model,
            object="response",
            output=[
                ResponseReasoningItem(
                    id=f"rs_{self._next_id()}",
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
            id=f"m{self._next_id()}",
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


# ---- Shared ContainerOptions fixtures and in-proc docker exec specs ----
# Kept here so all tests can reuse the same settings consistently.


@pytest.fixture
def container_opts_py312() -> ContainerOptions:
    return ContainerOptions(
        image="python:3.12-slim",
        working_dir="/workspace",
        volumes=None,
        describe=False,
    )


@pytest.fixture
def container_opts_py312_describe_true() -> ContainerOptions:
    return ContainerOptions(
        image="python:3.12-slim",
        working_dir="/workspace",
        volumes=None,
        describe=True,
    )


@pytest.fixture
def container_opts_alpine() -> ContainerOptions:
    return ContainerOptions(image="alpine:3.19", describe=False)


@pytest.fixture
def docker_exec_server_py312(container_opts_py312) -> object:
    return make_container_exec_mcp(container_opts_py312)


@pytest.fixture
def docker_exec_server_py312_describe_true(
    container_opts_py312_describe_true,
) -> object:
    return make_container_exec_mcp(container_opts_py312_describe_true)


@pytest.fixture
def docker_exec_server_alpine(container_opts_alpine) -> object:
    return make_container_exec_mcp(container_opts_alpine)


@pytest.fixture
def docker_inproc_spec_py312(docker_exec_server_py312) -> object:
    return make_inproc_slot_spec(docker_exec_server_py312)


@pytest.fixture
def docker_inproc_spec_py312_describe_true(
    docker_exec_server_py312_describe_true,
) -> object:
    return make_inproc_slot_spec(docker_exec_server_py312_describe_true)


@pytest.fixture
def docker_inproc_spec_alpine(docker_exec_server_alpine) -> object:
    return make_inproc_slot_spec(docker_exec_server_alpine)


@pytest.fixture
def docker_specs_py312(docker_inproc_spec_py312) -> dict[str, object]:
    return {"docker": docker_inproc_spec_py312}


@pytest.fixture
async def empty_mcp() -> McpManager:
    """A real McpManager with zero servers, entered for the test duration."""
    mgr = McpManager({})
    await mgr.__aenter__()
    try:
        yield mgr
    finally:
        await mgr.__aexit__(None, None, None)
