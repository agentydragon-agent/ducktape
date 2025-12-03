"""Integration tests for bootstrap handlers."""

from __future__ import annotations

from fastmcp.server import FastMCP
from pydantic import BaseModel
import pytest

from adgn.agent.bootstrap import TypedBootstrapBuilder
from adgn.agent.handler import SequenceHandler
from adgn.agent.loop_control import InjectItems, NoAction
from tests.support.assertions import is_all_function_calls


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
    """Bootstrap handler injects calls on first on_before_sample() and returns NoAction thereafter."""
    # Create builder with introspection (validates payload types)
    builder = TypedBootstrapBuilder.for_server(test_server)

    # Build calls - auto-generated call_ids
    calls = [
        builder.call("test_server", "test_tool", TestInput(value="foo")),
        builder.call("test_server", "test_tool", TestInput(value="bar")),
    ]

    # Create handler
    bootstrap = SequenceHandler([InjectItems(items=calls)])

    # First call: should inject calls via InjectItems
    decision = bootstrap.on_before_sample()
    assert isinstance(decision, InjectItems)
    assert len(decision.items) == 2

    # Verify call structure - use TypeGuard to narrow types
    assert is_all_function_calls(decision.items)
    first_call, second_call = decision.items

    assert first_call.name == "test_server_test_tool"
    assert first_call.call_id == "bootstrap:1"  # auto-generated

    assert second_call.name == "test_server_test_tool"
    assert second_call.call_id == "bootstrap:2"

    # Second call: should return NoAction (already injected)
    decision2 = bootstrap.on_before_sample()
    assert isinstance(decision2, NoAction)

    # Third call: should still return NoAction
    decision3 = bootstrap.on_before_sample()
    assert isinstance(decision3, NoAction)


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
