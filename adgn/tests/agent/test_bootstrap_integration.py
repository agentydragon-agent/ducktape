"""Integration tests for bootstrap handlers."""

from __future__ import annotations

from fastmcp.server import FastMCP
from pydantic import BaseModel
import pytest

from adgn.agent.bootstrap import BootstrapHandler, TypedBootstrapBuilder
from adgn.agent.loop_control import Continue, NoLoopDecision


class TestInput(BaseModel):
    """Test input model for fake MCP server."""

    value: str


class TestOutput(BaseModel):
    """Test output model for fake MCP server."""

    result: str


@pytest.fixture
def test_server() -> FastMCP:
    """Fake MCP server with a single test tool."""
    server = FastMCP("test_server")

    @server.tool()
    def test_tool(input: TestInput) -> TestOutput:
        return TestOutput(result=f"processed: {input.value}")

    return server


async def test_bootstrap_handler_injects_calls_before_first_sampling(test_server):
    """Bootstrap handler injects calls on first on_before_sample() and returns NoLoopDecision thereafter."""
    # Create builder with introspection (validates payload types)
    builder = TypedBootstrapBuilder.for_server(test_server)

    # Build calls - auto-generated call_ids
    calls = [
        builder.call("test_server", "test_tool", TestInput(value="foo")),
        builder.call("test_server", "test_tool", TestInput(value="bar")),
    ]

    # Create handler
    bootstrap = BootstrapHandler(calls)

    # First call: should inject calls via Continue with skip_sampling=True
    decision = bootstrap.on_before_sample()
    assert isinstance(decision, Continue)
    assert decision.skip_sampling is True
    assert len(decision.inserts_input) == 2

    # Verify call structure
    first_call = decision.inserts_input[0]
    assert first_call.name == "test_server_test_tool"
    assert first_call.call_id == "bootstrap:1"  # auto-generated

    second_call = decision.inserts_input[1]
    assert second_call.name == "test_server_test_tool"
    assert second_call.call_id == "bootstrap:2"

    # Second call: should return NoLoopDecision (already injected)
    decision2 = bootstrap.on_before_sample()
    assert isinstance(decision2, NoLoopDecision)

    # Third call: should still return NoLoopDecision
    decision3 = bootstrap.on_before_sample()
    assert isinstance(decision3, NoLoopDecision)


async def test_bootstrap_builder_accepts_any_payload_without_introspection(test_server):
    """TypedBootstrapBuilder without introspection accepts any Pydantic payload."""
    # Note: introspection may not work for all FastMCP configurations
    # This test verifies builder works with or without type validation
    builder = TypedBootstrapBuilder.for_server(test_server)

    # Valid payload: should succeed
    call = builder.call("test_server", "test_tool", TestInput(value="test"))
    assert call.name == "test_server_test_tool"

    # Different payload type: should succeed (no validation if introspection fails)
    class WrongInput(BaseModel):
        other_field: int

    call2 = builder.call("test_server", "test_tool", WrongInput(other_field=42))
    assert call2.name == "test_server_test_tool"


async def test_bootstrap_builder_auto_generates_call_ids(test_server):
    """TypedBootstrapBuilder auto-generates sequential call_ids."""
    builder = TypedBootstrapBuilder.for_server(test_server)

    # Build multiple calls - verify auto-increment
    call1 = builder.call("test_server", "test_tool", TestInput(value="a"))
    call2 = builder.call("test_server", "test_tool", TestInput(value="b"))
    call3 = builder.call("test_server", "test_tool", TestInput(value="c"))

    assert call1.call_id == "bootstrap:1"
    assert call2.call_id == "bootstrap:2"
    assert call3.call_id == "bootstrap:3"


async def test_bootstrap_builder_custom_call_id_prefix(test_server):
    """TypedBootstrapBuilder supports custom call_id prefix."""
    builder = TypedBootstrapBuilder.for_server(test_server, call_id_prefix="init")

    call = builder.call("test_server", "test_tool", TestInput(value="test"))
    assert call.call_id == "init:1"


async def test_bootstrap_builder_explicit_call_id(test_server):
    """TypedBootstrapBuilder accepts explicit call_id override."""
    builder = TypedBootstrapBuilder.for_server(test_server)

    call = builder.call("test_server", "test_tool", TestInput(value="test"), call_id="custom-id")
    assert call.call_id == "custom-id"


async def test_bootstrap_builder_without_introspection():
    """TypedBootstrapBuilder works without introspection (no type validation)."""
    # Create builder without server introspection
    builder = TypedBootstrapBuilder()

    # Should accept any payload without validation
    call = builder.call("unknown_server", "unknown_tool", TestInput(value="test"))
    assert call.name == "unknown_server_unknown_tool"
    assert call.call_id == "bootstrap:1"
