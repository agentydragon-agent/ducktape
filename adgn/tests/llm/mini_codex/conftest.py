from __future__ import annotations

from collections.abc import Callable, Iterable
import json
import os
import uuid
from typing import Any, AsyncIterator, Tuple
from pathlib import Path
from contextlib import asynccontextmanager

from adgn.llm.openai_utils.model import (
    ResponsesResult,
    Usage as PUsage,
    ReasoningOut,
    FunctionCallOut,
    AssistantResponseMessage,
    FakeOpenAIModel,
)
import pytest

from adgn.llm.mini_codex.mcp_manager import McpManager
from adgn.llm.mcp.testing.typed_stubs import TypedClient
from adgn.llm.mcp.editor_server import make_editor_mcp
from adgn.llm.mini_codex.approvals import (
    ApprovalPolicyEngine,
    ApprovalPolicyHandler,
    ApprovalHub,
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


# --- Pytest fixtures (prefer fixtures over cross-importing test modules) ---


@pytest.fixture
def approval_engine() -> ApprovalPolicyEngine:
    return ApprovalPolicyEngine()


@pytest.fixture
def approval_handler(approval_engine: ApprovalPolicyEngine) -> ApprovalPolicyHandler:
    return ApprovalPolicyHandler(approval_engine, ApprovalHub())


@pytest.fixture
def assistant_response_factory() -> Callable[[str, str], ResponsesResult]:
    def _make(model: str, text: str) -> ResponsesResult:
        return ResponsesResult(
            id="resp_msg",
            usage=PUsage(input_tokens=0, output_tokens=1, total_tokens=1),
            output=[AssistantResponseMessage(text=text)],
        )

    return _make


# Shared model fixture for live tests that need a reasoning-capable model
@pytest.fixture(scope="session")
def reasoning_model() -> str:
    # Default to gpt-5-nano for fast, reasoning-capable behavior; allow override via env
    return os.environ.get("RESPONSES_TEST_MODEL", "gpt-5-nano")


@pytest.fixture
def tool_call_response_factory() -> Callable[
    [str, str, str, dict[str, Any] | str], ResponsesResult
]:
    def _make(
        model: str, call_id: str, name: str, arguments: dict[str, Any] | str
    ) -> ResponsesResult:
        args_json = (
            json.dumps(arguments) if isinstance(arguments, dict) else str(arguments)
        )
        return ResponsesResult(
            id="resp_tc",
            usage=PUsage(input_tokens=0, output_tokens=0, total_tokens=0),
            output=[FunctionCallOut(call_id=call_id, name=name, arguments=args_json)],
        )

    return _make


# Convenience factory that bundles a model and helpers for creating our ResponsesResult outputs
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
    ) -> ResponsesResult:
        args_json = (
            json.dumps(arguments) if isinstance(arguments, dict) else str(arguments)
        )
        return ResponsesResult(
            id="resp_tc",
            usage=PUsage(input_tokens=0, output_tokens=0, total_tokens=0),
            output=[FunctionCallOut(call_id=call_id, name=name, arguments=args_json)],
        )

    def make_assistant_text_response(self, text: str) -> ResponsesResult:
        return ResponsesResult(
            id="resp_msg",
            usage=PUsage(input_tokens=0, output_tokens=1, total_tokens=1),
            output=[AssistantResponseMessage(text=text)],
        )

    def make_reasoning_then_tool(
        self,
        call_id: str,
        name: str,
        arguments: dict[str, Any],
    ) -> ResponsesResult:
        return ResponsesResult(
            id="resp_1",
            usage=PUsage(input_tokens=0, output_tokens=0, total_tokens=0),
            output=[
                ReasoningOut(id=f"rs_{self._next_id()}"),
                FunctionCallOut(
                    call_id=call_id, name=name, arguments=json.dumps(arguments)
                ),
            ],
        )

    def make_final_assistant(self, text: str) -> ResponsesResult:
        return ResponsesResult(
            id="resp_2",
            usage=PUsage(input_tokens=0, output_tokens=1, total_tokens=1),
            output=[AssistantResponseMessage(text=text)],
        )


@pytest.fixture(scope="session")
def responses_factory(reasoning_model: str) -> ResponsesFactory:
    """Provide a small factory bound to a reasoning-capable model for tests.

    Usage in tests:
      from tests.llm.support.openai_mock import FakeOpenAIClient

      def test_x(responses_factory):
          r = responses_factory.make_tool_call_response(...)
          client = FakeOpenAIClient([r, ...])
    """
    return ResponsesFactory(reasoning_model)


# Local factory: construct our Pydantic-only fake client from a sequence of ResponsesResult
@pytest.fixture
def fake_openai_client_factory() -> Callable[
    [Iterable[ResponsesResult]], FakeOpenAIModel
]:
    def _make(outputs: Iterable[ResponsesResult]) -> FakeOpenAIModel:
        return FakeOpenAIModel(list(outputs))

    return _make


# ---- Shared ContainerOptions fixtures and in-proc docker exec specs ----
# Kept here so all tests can reuse the same settings consistently.


@pytest.fixture
async def empty_mcp() -> McpManager:
    """A real McpManager with zero servers, entered for the test duration."""
    mgr = McpManager({})
    await mgr.__aenter__()
    try:
        yield mgr
    finally:
        await mgr.__aexit__(None, None, None)


@pytest.fixture
def typed_editor_factory(tmp_path: Path, make_typed_mcp):
    """Factory that yields (TypedClient, target_path) for an in-proc editor server."""

    @asynccontextmanager
    async def _open(
        initial_text: str = "x = 1\n",
    ) -> AsyncIterator[Tuple[TypedClient, Path]]:
        target = tmp_path / "sample.py"
        target.write_text(initial_text, encoding="utf-8")
        srv = make_editor_mcp(target)
        async with make_typed_mcp(srv, "editor") as (client, _session):
            yield client, target

    return _open
