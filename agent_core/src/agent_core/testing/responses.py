"""Response factories and step runner for agent tests.

Provides declarative test response building:
- ResponsesFactory: Builds mock ResponsesResult objects
- StepRunner: Executes declarative test steps as an OpenAIModelProto
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from mcp import types as mcp_types
from pydantic import BaseModel, TypeAdapter

from mcp_infra.exec.docker.server import ContainerExecServer
from mcp_infra.exec.models import ExecInput
from mcp_infra.naming import MCPMountPrefix, build_mcp_function
from openai_utils.builders import ItemFactory
from openai_utils.model import (
    AssistantMessageOut,
    FunctionCallItem,
    FunctionCallOutputItem,
    InputTokensDetails,
    OpenAIModelProto,
    OutputTokensDetails,
    ReasoningItem,
    ResponseOutItem,
    ResponsesRequest,
    ResponsesResult,
    ResponseUsage,
)

if TYPE_CHECKING:
    from agent_core.testing.steps import Step

logger = logging.getLogger(__name__)


class ResponsesFactory:
    """Convenience adapter response builders bound to a model name.

    Provides methods to build mock ResponsesResult objects for testing.
    """

    def __init__(self, model: str):
        self.model = model
        self._item_factory = ItemFactory(call_id_prefix="test")
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

    def make_mcp_tool_call(self, server: MCPMountPrefix, tool: str, arguments: BaseModel) -> ResponsesResult:
        """Create tool call response for MCP server/tool with automatic naming."""
        return self.make(self.mcp_tool_call(server, tool, arguments))

    # ---- Low-level item builders (compose with make(...items)) ----

    def assistant_text(self, text: str) -> AssistantMessageOut:
        return self._item_factory.assistant_text(text)

    def tool_call(self, name: str, arguments: dict[str, Any], call_id: str | None = None) -> FunctionCallItem:
        return self._item_factory.tool_call(name, arguments, call_id)

    def mcp_tool_call(
        self, server: MCPMountPrefix, tool: str, arguments: BaseModel, call_id: str | None = None
    ) -> FunctionCallItem:
        """Create tool call for MCP server/tool with automatic naming."""
        return self._item_factory.tool_call(
            build_mcp_function(server, tool), arguments.model_dump(mode="json"), call_id
        )

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
        self, server: MCPMountPrefix, tool: str, arguments: BaseModel, output: Any
    ) -> ResponsesResult:
        """Create paired tool call + output for MCP server/tool."""
        return self._make_call_with_output(self.mcp_tool_call(server, tool, arguments), output)

    def docker_exec(
        self,
        cmd: list[str],
        *,
        timeout_ms: int = 30000,
        cwd: Path | None = None,
        env: list[str] | None = None,
        user: str | None = None,
        tool_name: str = "exec",
    ) -> FunctionCallItem:
        """Create docker exec tool call with sensible defaults."""
        exec_input = ExecInput(cmd=cmd, cwd=str(cwd) if cwd else None, env=env, user=user, timeout_ms=timeout_ms)
        return self.mcp_tool_call(ContainerExecServer.DOCKER_MOUNT_PREFIX, tool_name, exec_input)


class StepRunner(OpenAIModelProto):
    """Step-based OpenAI mock that executes declarative test steps.

    Implements OpenAIModelProto directly, so can be used as the client parameter
    to agent functions without any wrapping.

    Usage:
        runner = make_step_runner(steps=[AssistantMessage("Done")])
        result = await agent.run(..., client=runner)

    Debug logging:
        To see step execution with timestamps (for timeout tuning):
            pytest --log-cli-level=DEBUG tests/path/to/test.py
    """

    def __init__(self, factory: ResponsesFactory, steps: Sequence[Step]) -> None:
        self.factory: ResponsesFactory = factory
        self.steps: Sequence[Step] = steps
        self.turn: int = 0
        self.model = "test-model"

    @property
    def current_step_index(self) -> int:
        """Current step index (0-based). Alias for turn for clarity."""
        return self.turn

    async def responses_create(self, req: ResponsesRequest) -> ResponsesResult:
        """Execute current step and advance. Implements OpenAIModelProto."""
        if self.turn >= len(self.steps):
            pytest.fail(f"Exceeded {len(self.steps)} expected turns (got turn {self.turn + 1})")
        step = self.steps[self.turn]
        step_type = type(step).__name__
        logger.debug("Step %d/%d (%s)", self.turn + 1, len(self.steps), step_type)
        result = step.execute(req, self.factory)
        self.turn += 1
        return result


# ---- Pytest fixtures ----


@pytest.fixture(scope="session")
def reasoning_model() -> str:
    """Default reasoning-capable model for adapter fixtures.

    Tests may override via RESPONSES_TEST_MODEL env.
    """
    return os.environ.get("RESPONSES_TEST_MODEL", "gpt-5-nano")


@pytest.fixture(scope="session")
def responses_factory(reasoning_model: str) -> ResponsesFactory:
    return ResponsesFactory(reasoning_model)


@pytest.fixture
def make_step_runner(responses_factory: ResponsesFactory):
    """Factory fixture that creates step runners.

    Returns a factory function that creates StepRunner instances.
    """

    def _make(steps: Sequence[Step]) -> StepRunner:
        return StepRunner(factory=responses_factory, steps=steps)

    return _make
