from __future__ import annotations

from typing import Literal

from fastmcp.server import FastMCP
from pydantic import BaseModel, Field
import pytest

from adgn.mcp._shared.fastmcp_flat import FlatModelFastMCP, mcp_flat_model


class EchoInput(BaseModel):
    msg: str = Field(description="Message to echo")
    upper: bool = Field(default=False, description="Uppercase the message")


class EchoOutput(BaseModel):
    kind: Literal["Echo"] = "Echo"
    text: str


def make_echo_server():
    mcp = FlatModelFastMCP("echo")

    @mcp.tool(
        name="echo",
        title="Echo",
        description="Echo a message",
        structured_output=True,
        flat=True,
    )
    def echo(input: EchoInput) -> EchoOutput:
        text = input.msg.upper() if input.upper else input.msg
        return EchoOutput(text=text)

    return mcp


@pytest.mark.asyncio
async def test_flat_schema_and_typed_invocation(make_typed_mcp):
    server = make_echo_server()

    async with make_typed_mcp(server, "echo") as (client, sess):
        # Fast path: typed client can call tool like client.echo(EchoInput(...)) -> EchoOutput
        EchoIn = client.models["echo"].Input
        assert EchoIn is EchoInput

        out = await client.echo(EchoInput(msg="hi", upper=True))
        assert isinstance(out, EchoOutput)
        assert out.text == "HI"

        # Validate server advertises flat arguments (no nested 'input')
        tools = getattr(server, "_tool_manager").list_tools()
        tool = next(t for t in tools if t.name == "echo")
        schema = tool.parameters
        props = schema.get("properties", {})
        assert set(props.keys()) >= {"msg", "upper"}  # flat keys present
        # Ensure not wrapped
        assert "input" not in props


def test_mcp_flat_model_backward_compatibility():
    legacy = FastMCP("legacy")

    @mcp_flat_model(legacy, name="legacy_echo", structured_output=False)
    def legacy_echo(input: EchoInput):
        return {"text": input.msg}

    tools = getattr(legacy, "_tool_manager").list_tools()
    tool = next(t for t in tools if t.name == "legacy_echo")
    props = tool.parameters.get("properties", {})
    assert "msg" in props
    assert "upper" in props
    assert "input" not in props


def test_tool_flat_explicit_models():
    mcp = FlatModelFastMCP("echo2")

    @mcp.tool(name="echo", flat=True, flat_output_model=EchoOutput)
    def echo_again(payload: EchoInput) -> EchoOutput:
        return EchoOutput(text=payload.msg)

    tools = getattr(mcp, "_tool_manager").list_tools()
    tool = next(t for t in tools if t.name == "echo")
    props = tool.parameters.get("properties", {})
    assert set(props) >= {"msg", "upper"}
