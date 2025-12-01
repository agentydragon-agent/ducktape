from __future__ import annotations

from collections.abc import Sequence
import os
from typing import TYPE_CHECKING, Any

from fastmcp.client.client import CallToolResult
from openai.types.responses.response_usage import InputTokensDetails, OutputTokensDetails, ResponseUsage
from pydantic import BaseModel, TypeAdapter
import pytest

from adgn.mcp._shared.naming import build_mcp_function
from adgn.openai_utils import builders
from adgn.openai_utils.model import (
    AssistantMessageOut,
    FunctionCallItem,
    FunctionCallOutputItem,
    ReasoningItem,
    ResponseOutItem,
    ResponsesRequest,
    ResponsesResult,
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
        result: ResponsesResult = ResponsesResult(
            id="resp_msg",
            usage=ResponseUsage(
                input_tokens=0,
                input_tokens_details=InputTokensDetails(cached_tokens=0),
                output_tokens=1,
                output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
                total_tokens=1,
            ),
            output=[self._item_factory.assistant_text(text)],
        )
        return result

    def make_tool_call(self, name: str, arguments: dict[str, Any], call_id: str | None = None) -> ResponsesResult:
        result: ResponsesResult = self.make(self._item_factory.tool_call(name, arguments, call_id))
        return result

    def make_mcp_tool_call(
        self, server: str, tool: str, input_model: BaseModel, call_id: str | None = None
    ) -> ResponsesResult:
        """Create a tool call response for an MCP tool with typed input.

        Args:
            server: MCP server name
            tool: MCP tool name
            input_model: Pydantic input model instance
            call_id: Optional call ID

        Returns:
            ResponsesResult with the tool call
        """
        name = build_mcp_function(server, tool)
        arguments = input_model.model_dump()
        return self.make_tool_call(name, arguments, call_id)

    # ---- Low-level item builders (compose with make(...items)) ----

    def assistant_text(self, text: str) -> AssistantMessageOut:
        """Create an assistant text item. Delegates to ItemFactory."""
        return self._item_factory.assistant_text(text)

    def tool_call(self, name: str, arguments: dict[str, Any], call_id: str | None = None) -> FunctionCallItem:
        """Create a tool call item. Delegates to ItemFactory."""
        return self._item_factory.tool_call(name, arguments, call_id)

    def make_item_reasoning(self, id: str | None = None) -> ReasoningItem:
        return ReasoningItem(id=id or f"rs_{self._next_reasoning_id()}")

    def make_item_tool_call_auto(self, name: str, arguments: dict[str, Any]) -> FunctionCallItem:
        return self._item_factory.tool_call(name, arguments)

    # ---- Message/response constructors (compose items) ----

    def make(self, *items: ResponseOutItem) -> ResponsesResult:
        # Minimal usage heuristic: count assistant text parts as output tokens >=1
        out_tokens = 0
        for it in items:
            if isinstance(it, AssistantMessageOut):
                out_tokens += max(1, len(it.text))
        usage = ResponseUsage(
            input_tokens=0,
            input_tokens_details=InputTokensDetails(cached_tokens=0),
            output_tokens=(1 if out_tokens else 0),
            output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
            total_tokens=(1 if out_tokens else 0),
        )
        # Coerce any plain dicts to proper models if needed (not expected here)
        result: ResponsesResult = ResponsesResult(id="resp_generic", usage=usage, output=list(items))
        return result

    def make_tool_call_auto(self, name: str, arguments: dict[str, Any]) -> ResponsesResult:
        result: ResponsesResult = self.make(self.make_item_tool_call_auto(name, arguments))
        return result

    def make_final_assistant(self, text: str) -> ResponsesResult:
        result: ResponsesResult = self.make(self._item_factory.assistant_text(text))
        return result

    def make_reasoning_then_assistant(self, text: str) -> ResponsesResult:
        result: ResponsesResult = self.make(self.make_item_reasoning(), self._item_factory.assistant_text(text))
        return result

    def make_reasoning_tool_then_assistant(
        self, *, call_id: str, name: str, arguments: dict[str, Any], text: str
    ) -> ResponsesResult:
        result: ResponsesResult = self.make(
            self.make_item_reasoning(),
            self._item_factory.tool_call(name, arguments, call_id),
            self._item_factory.assistant_text(text),
        )
        return result

    def make_tool_call_with_output(
        self, name: str, arguments: dict[str, Any], output: Any, call_id: str | None = None
    ) -> ResponsesResult:
        call = self._item_factory.tool_call(name, arguments, call_id)
        tool_result = CallToolResult(content=[], structured_content=output, is_error=False, meta=None)
        payload_json = TypeAdapter(CallToolResult).dump_json(tool_result, by_alias=True)
        out = FunctionCallOutputItem(call_id=call.call_id, output=payload_json.decode("utf-8"))
        result: ResponsesResult = self.make(call, out)
        return result


class _StepRunner:
    """Generic state machine driven by declarative steps.

    Use as a context manager to get automatic validation that all steps completed:
        with _StepRunner(factory, steps) as runner:
            # Use runner
            pass
        # Validates all steps executed on exit
    """

    def __init__(self, factory: ResponsesFactory, steps: Sequence[Step]) -> None:
        self.factory: ResponsesFactory = factory
        self.steps: Sequence[Step] = steps
        self.turn: int = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Only validate if no exception occurred during test
        if exc_type is None and self.turn != len(self.steps):
            pytest.fail(f"Step runner incomplete: executed {self.turn}/{len(self.steps)} steps")
        return False

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
            with runner:
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
