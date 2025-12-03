from __future__ import annotations

from collections.abc import Sequence
import os
from typing import TYPE_CHECKING, Any

from mcp import types as mcp_types
from pydantic import BaseModel, TypeAdapter
import pytest

from adgn.openai_utils import builders
from adgn.openai_utils.model import (
    AssistantMessageOut,
    FunctionCallItem,
    FunctionCallOutputItem,
    InputTokensDetails,
    OutputTokensDetails,
    ReasoningItem,
    ResponseOutItem,
    ResponsesRequest,
    ResponsesResult,
    ResponseUsage,
)
from tests.llm.support.openai_mock import LIVE, make_mock

if TYPE_CHECKING:
    from tests.support.steps import Step


@pytest.fixture(scope="session")
def reasoning_model() -> str:
    """Default reasoning-capable model for adapter fixtures.

    Tests may override via RESPONSES_TEST_MODEL env.
    """
    return os.environ.get("RESPONSES_TEST_MODEL", "gpt-5-nano")


class ResponsesFactory:
    """Convenience adapter response builders bound to a model name."""

    def __init__(self, model: str):
        self.model = model
        self._item_factory = builders.ItemFactory(call_id_prefix="test")
        self._reasoning_seq = 0

    def _next_reasoning_id(self) -> int:
        self._reasoning_seq += 1
        return self._reasoning_seq

    def make_assistant_message(self, text: str) -> ResponsesResult:
        return ResponsesResult(
            id="resp_msg",
            usage=ResponseUsage(
                input_tokens=0,
                input_tokens_details=InputTokensDetails(cached_tokens=0),
                output_tokens=1,
                output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
                total_tokens=1,
            ),
            output=[self.assistant_text(text)],
        )

    def make_tool_call(self, name: str, arguments: dict[str, Any], call_id: str | None = None) -> ResponsesResult:
        return self.make(self.tool_call(name, arguments, call_id))

    # ---- Low-level item builders (compose with make(...items)) ----

    def assistant_text(self, text: str) -> AssistantMessageOut:
        return self._item_factory.assistant_text(text)

    def tool_call(self, name: str, arguments: dict[str, Any], call_id: str | None = None) -> FunctionCallItem:
        return self._item_factory.tool_call(name, arguments, call_id)

    def mcp_tool_call(
        self, server: str, tool: str, arguments: BaseModel, call_id: str | None = None
    ) -> FunctionCallItem:
        return self._item_factory.mcp_tool_call(server, tool, arguments, call_id)

    def make_mcp_tool_call(self, server: str, tool: str, arguments: BaseModel) -> ResponsesResult:
        """Create tool call response for MCP server/tool with automatic naming."""
        return self.make(self.mcp_tool_call(server, tool, arguments))

    def make_item_reasoning(self, id: str | None = None) -> ReasoningItem:
        return ReasoningItem(id=id or f"rs_{self._next_reasoning_id()}")

    # ---- Message/response constructors (compose items) ----

    def make(self, *items: ResponseOutItem) -> ResponsesResult:
        out_tokens = sum(max(1, len(it.text)) for it in items if isinstance(it, AssistantMessageOut))
        return ResponsesResult(
            id="resp_generic",
            usage=ResponseUsage(
                input_tokens=0,
                input_tokens_details=InputTokensDetails(cached_tokens=0),
                output_tokens=(1 if out_tokens else 0),
                output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
                total_tokens=(1 if out_tokens else 0),
            ),
            output=list(items),
        )

    def make_final_assistant(self, text: str) -> ResponsesResult:
        return self.make(self.assistant_text(text))

    def make_reasoning_then_assistant(self, text: str) -> ResponsesResult:
        return self.make(self.make_item_reasoning(), self.assistant_text(text))

    def _make_output_item(self, call_id: str, output: Any) -> FunctionCallOutputItem:
        """Create FunctionCallOutputItem from structured output."""
        tool_result = mcp_types.CallToolResult(content=[], structuredContent=output, isError=False)
        payload_json = TypeAdapter(mcp_types.CallToolResult).dump_json(tool_result, by_alias=True)
        return FunctionCallOutputItem(call_id=call_id, output=payload_json.decode("utf-8"))

    def _make_call_with_output(self, call: FunctionCallItem, output: Any) -> ResponsesResult:
        return self.make(call, self._make_output_item(call.call_id, output))

    def make_tool_call_with_output(
        self, name: str, arguments: dict[str, Any], output: Any, call_id: str | None = None
    ) -> ResponsesResult:
        return self._make_call_with_output(self.tool_call(name, arguments, call_id), output)

    def make_mcp_tool_call_with_output(
        self, server: str, tool: str, arguments: BaseModel, output: Any
    ) -> ResponsesResult:
        """Create paired tool call + output for MCP server/tool."""
        return self._make_call_with_output(self.mcp_tool_call(server, tool, arguments), output)


class _StepRunner:
    """Internal: Generic state machine driven by declarative steps."""

    def __init__(self, factory: ResponsesFactory, steps: Sequence[Step]) -> None:
        self.factory: ResponsesFactory = factory
        self.steps: Sequence[Step] = steps
        self.turn: int = 0

    def handle_request(self, req: ResponsesRequest) -> ResponsesResult:
        """Sync entry point - checks bounds and executes current step."""
        if self.turn >= len(self.steps):
            pytest.fail(f"Exceeded {len(self.steps)} expected turns (got turn {self.turn + 1})")
        result = self.steps[self.turn].execute(req, self.factory)
        self.turn += 1
        return result

    async def handle_request_async(self, req: ResponsesRequest) -> ResponsesResult:
        """Async wrapper for handle_request.

        Use with make_mock() to create a mock client:
            from tests.llm.support.openai_mock import make_mock
            client = make_mock(runner.handle_request_async)
        """
        return self.handle_request(req)


@pytest.fixture(scope="session")
def responses_factory(reasoning_model: str) -> ResponsesFactory:
    return ResponsesFactory(reasoning_model)


@pytest.fixture
def openai_client_param(request, live_openai):
    """Parametrized OpenAI client fixture for tests.

    Usage (indirect): parametrize with either a behavior function or LIVE sentinel:
        @pytest.mark.parametrize("openai_client_param", [behavior_fn, LIVE], indirect=True)

    - If parameter is LIVE, returns the live_openai fixture (AsyncOpenAI or skip if not set).
    - Otherwise, assumes a behavior function(req) -> ResponsesResult and returns a mock client.
    """
    param = getattr(request, "param", None)
    if param is LIVE:
        return live_openai
    if callable(param):
        return make_mock(param)
    pytest.skip("openai_client_param requires a behavior function or LIVE sentinel")
