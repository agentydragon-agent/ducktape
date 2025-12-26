import json
from typing import Any

from hamcrest import all_of, assert_that, equal_to, has_length, has_properties, has_property, instance_of
from hamcrest.core.base_matcher import BaseMatcher
from hamcrest.core.description import Description
from pydantic import BaseModel

from agent_core.testing import ResponsesFactory
from mcp_infra.exec.docker.server import ContainerExecServer
from mcp_infra.prefix import MCPMountPrefix
from mcp_infra.testing.simple_servers import ECHO_MOUNT_PREFIX, ECHO_TOOL_NAME
from openai_utils.model import FunctionCallItem, FunctionCallOutputItem


class SampleInput(BaseModel):
    text: str
    count: int = 1


class SampleOutput(BaseModel):
    result: str


class HasJsonArguments(BaseMatcher[FunctionCallItem]):
    """Matcher that checks FunctionCallItem has non-None arguments matching expected JSON."""

    def __init__(self, expected: dict[str, Any]):
        self.expected = expected

    def _matches(self, item: Any) -> bool:
        if not isinstance(item, FunctionCallItem):
            return False
        if item.arguments is None:
            return False
        try:
            return bool(json.loads(item.arguments) == self.expected)
        except (json.JSONDecodeError, TypeError):
            return False

    def describe_to(self, description: Description) -> None:
        description.append_text(f"FunctionCallItem with arguments matching {self.expected}")

    def describe_mismatch(self, item: Any, mismatch_description: Description) -> None:
        if not isinstance(item, FunctionCallItem):
            mismatch_description.append_text(f"was {type(item).__name__}")
        elif item.arguments is None:
            mismatch_description.append_text("had None arguments")
        else:
            try:
                actual = json.loads(item.arguments)
                mismatch_description.append_text(f"arguments were {actual}")
            except (json.JSONDecodeError, TypeError) as e:
                mismatch_description.append_text(f"arguments were not valid JSON: {e}")


class HasJsonOutput(BaseMatcher[FunctionCallOutputItem]):
    """Matcher that checks FunctionCallOutputItem has non-None output matching expected JSON.

    Handles both string (JSON) and list (multimodal) output formats.
    For string output, parses as JSON and compares.
    For list output, compares directly (since lists aren't JSON-parseable).
    """

    def __init__(self, expected: dict[str, Any]):
        self.expected = expected

    def _matches(self, item: Any) -> bool:
        if not isinstance(item, FunctionCallOutputItem):
            return False
        if item.output is None:
            return False
        # Handle both string (JSON) and list output
        if isinstance(item.output, str):
            try:
                return bool(json.loads(item.output) == self.expected)
            except json.JSONDecodeError:
                return False
        # For list output, can't JSON parse - compare directly if expected is dict representation
        return False

    def describe_to(self, description: Description) -> None:
        description.append_text(f"FunctionCallOutputItem with output matching {self.expected}")

    def describe_mismatch(self, item: Any, mismatch_description: Description) -> None:
        if not isinstance(item, FunctionCallOutputItem):
            mismatch_description.append_text(f"was {type(item).__name__}")
        elif item.output is None:
            mismatch_description.append_text("had None output")
        elif isinstance(item.output, str):
            try:
                actual = json.loads(item.output)
                mismatch_description.append_text(f"output was {actual}")
            except json.JSONDecodeError as e:
                mismatch_description.append_text(f"output was not valid JSON: {e}")
        else:
            mismatch_description.append_text(f"output was list: {item.output}")


def has_json_arguments(expected: dict[str, Any]) -> HasJsonArguments:
    """Create matcher for FunctionCallItem with specific JSON arguments."""
    return HasJsonArguments(expected)


def has_json_output(expected: dict[str, Any]) -> HasJsonOutput:
    """Create matcher for FunctionCallOutputItem with specific JSON output."""
    return HasJsonOutput(expected)


def test_responses_factory_mcp_tool_call_explicit_id(responses_factory: ResponsesFactory):
    """Test ResponsesFactory.mcp_tool_call with explicit call_id."""
    call = responses_factory.mcp_tool_call(
        ECHO_MOUNT_PREFIX, ECHO_TOOL_NAME, SampleInput(text="hello", count=2), call_id="call_1"
    )

    assert_that(
        call,
        all_of(
            instance_of(FunctionCallItem),
            has_properties(name="echo_echo", call_id="call_1"),
            has_json_arguments({"text": "hello", "count": 2}),
        ),
    )


def test_responses_factory_mcp_tool_call_auto_id(responses_factory: ResponsesFactory):
    """Test ResponsesFactory.mcp_tool_call with auto-generated call_id."""
    call = responses_factory.mcp_tool_call(MCPMountPrefix("server"), "tool", SampleInput(text="test"))

    assert call.name == "server_tool"
    assert call.call_id.startswith("test:")  # Uses factory's call_id_prefix


def test_responses_factory_make_mcp_tool_call(responses_factory: ResponsesFactory):
    result = responses_factory.make_mcp_tool_call(
        ContainerExecServer.DOCKER_MOUNT_PREFIX, ContainerExecServer.EXEC_TOOL_NAME, SampleInput(text="ls")
    )

    assert_that(result, has_properties(id="resp_generic"))
    assert_that(result.output, has_length(1))
    call_item = result.output[0]
    assert_that(
        call_item,
        all_of(
            instance_of(FunctionCallItem),
            has_properties(name="docker_exec"),
            has_property("call_id"),  # auto-generated, just check it exists
            has_json_arguments({"text": "ls", "count": 1}),
        ),
    )


def test_responses_factory_mcp_tool_call_item(responses_factory: ResponsesFactory):
    call = responses_factory.mcp_tool_call(
        ContainerExecServer.RUNTIME_MOUNT_PREFIX, ContainerExecServer.EXEC_TOOL_NAME, SampleInput(text="echo")
    )

    assert_that(
        call,
        all_of(
            instance_of(FunctionCallItem),
            has_properties(name="runtime_exec"),
            has_json_arguments({"text": "echo", "count": 1}),
        ),
    )


def test_responses_factory_make_mcp_tool_call_with_output(responses_factory: ResponsesFactory):
    result = responses_factory.make_mcp_tool_call_with_output(
        ECHO_MOUNT_PREFIX, ECHO_TOOL_NAME, SampleInput(text="hello"), {"echo": "hello"}
    )

    assert_that(result.output, has_length(2))
    call_item, output_item = result.output

    # Type narrowing for mypy
    assert isinstance(call_item, FunctionCallItem)
    assert isinstance(output_item, FunctionCallOutputItem)

    assert_that(
        call_item,
        all_of(
            instance_of(FunctionCallItem),
            has_properties(name="echo_echo"),
            has_property("call_id"),  # auto-generated
        ),
    )
    assert_that(
        output_item,
        all_of(
            instance_of(FunctionCallOutputItem),
            has_properties(call_id=equal_to(call_item.call_id)),  # output matches call
            has_json_output({"_meta": None, "content": [], "structuredContent": {"echo": "hello"}, "isError": False}),
        ),
    )


def test_mcp_tool_call_composes_with_make(responses_factory: ResponsesFactory):
    result = responses_factory.make(
        responses_factory.make_item_reasoning(),
        responses_factory.mcp_tool_call(MCPMountPrefix("server"), "tool", SampleInput(text="test")),
        responses_factory.assistant_text("done"),
    )

    assert_that(result.output, has_length(3))
    _reasoning, call, _text = result.output
    assert_that(call, has_properties(name="server_tool"))
