import json

from pydantic import BaseModel

from adgn.openai_utils.builders import ItemFactory
from adgn.openai_utils.model import FunctionCallItem
from tests.support.responses import ResponsesFactory


class SampleInput(BaseModel):
    text: str
    count: int = 1


class SampleOutput(BaseModel):
    result: str


def test_item_factory_mcp_tool_call():
    factory = ItemFactory(call_id_prefix="test")
    call = factory.mcp_tool_call("echo", "echo", SampleInput(text="hello", count=2), call_id="call_1")

    assert isinstance(call, FunctionCallItem)
    assert call.name == "echo_echo"
    assert call.call_id == "call_1"
    assert json.loads(call.arguments) == {"text": "hello", "count": 2}


def test_item_factory_mcp_tool_call_auto_id():
    factory = ItemFactory(call_id_prefix="auto")
    call = factory.mcp_tool_call("server", "tool", SampleInput(text="test"))

    assert call.name == "server_tool"
    assert call.call_id == "auto:1"


def test_responses_factory_make_mcp_tool_call(responses_factory: ResponsesFactory):
    result = responses_factory.make_mcp_tool_call("docker", "exec", SampleInput(text="ls"))

    assert result.id == "resp_generic"
    assert len(result.output) == 1
    call_item = result.output[0]
    assert isinstance(call_item, FunctionCallItem)
    assert call_item.name == "docker_exec"
    assert call_item.call_id  # auto-generated
    assert json.loads(call_item.arguments) == {"text": "ls", "count": 1}


def test_responses_factory_mcp_tool_call_item(responses_factory: ResponsesFactory):
    call = responses_factory.mcp_tool_call("runtime", "exec", SampleInput(text="echo"))

    assert isinstance(call, FunctionCallItem)
    assert call.name == "runtime_exec"
    assert json.loads(call.arguments) == {"text": "echo", "count": 1}


def test_responses_factory_make_mcp_tool_call_with_output(responses_factory: ResponsesFactory):
    result = responses_factory.make_mcp_tool_call_with_output(
        "echo", "echo", SampleInput(text="hello"), {"echo": "hello"}
    )

    assert len(result.output) == 2
    call_item, output_item = result.output
    assert isinstance(call_item, FunctionCallItem)
    assert call_item.name == "echo_echo"
    assert call_item.call_id  # auto-generated
    assert output_item.call_id == call_item.call_id  # output matches call
    output_data = json.loads(output_item.output)
    assert output_data["structured_content"] == {"echo": "hello"}
    assert output_data["is_error"] is False


def test_mcp_tool_call_composes_with_make(responses_factory: ResponsesFactory):
    result = responses_factory.make(
        responses_factory.make_item_reasoning(),
        responses_factory.mcp_tool_call("server", "tool", SampleInput(text="test")),
        responses_factory.assistant_text("done"),
    )

    assert len(result.output) == 3
    reasoning, call, text = result.output
    assert call.name == "server_tool"
