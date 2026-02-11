"""Declarative step classes for test agent state machines.

See docs/test_scenario_steps.md for detailed usage guide.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel

from adgn.openai_utils.model import ResponsesRequest, ResponsesResult
from tests.support.assertions import assert_and_extract, assert_last_call
from tests.support.responses import ResponsesFactory

T = TypeVar("T", bound=BaseModel)


class Step(Protocol):
    """Protocol for step objects that can be executed in sequence."""

    def execute(self, req: ResponsesRequest, factory: ResponsesFactory) -> ResponsesResult: ...


@dataclass
class MakeCall:
    """Initial turn: make a tool call."""

    server: str
    tool: str
    args: BaseModel

    def execute(self, req: ResponsesRequest, factory: ResponsesFactory) -> ResponsesResult:
        return factory.make_mcp_tool_call(self.server, self.tool, self.args)


@dataclass
class CheckThenCall:
    """Assert previous tool completed, then call next."""

    expected_tool: str
    server: str
    tool: str
    args: BaseModel

    def execute(self, req: ResponsesRequest, factory: ResponsesFactory) -> ResponsesResult:
        assert_last_call(req, self.expected_tool)
        return factory.make_mcp_tool_call(self.server, self.tool, self.args)


@dataclass
class ExtractThenCall[T: BaseModel]:
    """Extract typed output from previous call, use in next call."""

    expected_tool: str
    output_type: type[T]
    make_next: Callable[[T], tuple[str, str, BaseModel]]

    def execute(self, req: ResponsesRequest, factory: ResponsesFactory) -> ResponsesResult:
        output = assert_and_extract(req, self.expected_tool, self.output_type)
        server, tool, args = self.make_next(output)
        return factory.make_mcp_tool_call(server, tool, args)


@dataclass
class Finish:
    """Final turn: assert completion and return message."""

    expected_tool: str
    message: str = "Done"

    def execute(self, req: ResponsesRequest, factory: ResponsesFactory) -> ResponsesResult:
        assert_last_call(req, self.expected_tool)
        return factory.make_assistant_message(self.message)


@dataclass
class AssistantMessage:
    """Return assistant message without checking previous tool.

    Use for simple sequences where you don't need to validate tool completion.
    For complex workflows, prefer Finish which validates the final tool.
    """

    message: str

    def execute(self, req: ResponsesRequest, factory: ResponsesFactory) -> ResponsesResult:
        return factory.make_assistant_message(self.message)
