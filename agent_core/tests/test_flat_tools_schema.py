"""Test agent with 2 flat tool decorator MCP servers showing full OpenAI request schema.

This test demonstrates how schemas from flat tool decorators are passed to the LLM,
including complex nested models with Annotated fields, regex patterns, and descriptions.
"""

from __future__ import annotations

import json
from typing import Annotated, Final, Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field

from agent_core.agent import Agent
from agent_core.handler import FinishOnTextMessageHandler
from agent_core.loop_control import RequireAnyTool
from agent_core_testing.responses import DecoratorMock
from mcp_infra.enhanced.server import EnhancedFastMCP
from mcp_infra.prefix import MCPMountPrefix
from openai_utils.model import SystemMessage

# Test tool name constant
TOOL_A_NAME: Final[str] = "tool_a"

# ============================================================================
# Server A: Simple tool - Models at module scope
# ============================================================================


class ToolAInput(BaseModel):
    """Input for tool A."""

    model_config = ConfigDict(extra="forbid")

    param_x: float = Field(description="First parameter")
    param_y: float = Field(description="Second parameter")


class ToolAResult(BaseModel):
    """Result of tool A."""

    value: float = Field(description="Computed result value")


@pytest.fixture
def mcp_a() -> EnhancedFastMCP:
    """Create MCP server A with a simple flat tool."""
    mcp = EnhancedFastMCP()

    @mcp.flat_model()
    def tool_a(input: ToolAInput) -> ToolAResult:
        """Perform tool A on the inputs."""
        return ToolAResult(value=input.param_x + input.param_y)

    return mcp


# ============================================================================
# Server B: Complex tool with nested models - Models at module scope
# ============================================================================


class NestedInfo(BaseModel):
    """Nested information block."""

    model_config = ConfigDict(extra="forbid")

    regex: Annotated[str, Field(description="Regex validation", pattern=r"^\d{5}$")]
    text_defaultd: str = Field(default="DEFAULT", description="Text with default")


class CategoryInfo(BaseModel):
    """Category classification."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["type_a", "type_b", "type_c"] = Field(default="type_b")


class ToolBInput(BaseModel):
    """Complete tool B request.

    Exercises nested models, annotated fields with regex validation, field-level
    descriptions, model-level documentation.
    """

    model_config = ConfigDict(extra="forbid")

    identifier: Annotated[str, Field(description="Required regex field", pattern=r"^[a-z]{3}$")]
    count: int = Field(description="Int with range", ge=10, le=100)
    nested: NestedInfo
    category: CategoryInfo = Field(default_factory=lambda: CategoryInfo(type="type_b"))
    flag: bool = Field(default=False, description="Boolean with default")


class ResponseA(BaseModel):
    """Success response variant A."""

    status: Literal["success"] = "success"
    message: str = Field(description="Status message")


class ResponseB(BaseModel):
    """Error response variant B."""

    status: Literal["error"] = "error"
    error_code: str = Field(description="Machine-readable error code")
    message: str = Field(description="Human-readable error description")


ToolBResult = Annotated[ResponseA | ResponseB, Field(discriminator="status")]


@pytest.fixture
def mcp_b() -> EnhancedFastMCP:
    """Create MCP server B with complex nested schema."""
    mcp = EnhancedFastMCP()

    @mcp.flat_model()
    def tool_b(input: ToolBInput) -> ToolBResult:
        """Perform tool B with complex validation."""
        return ResponseB(error_code="TEST", message="test")

    return mcp


async def test_agent_compositor_flat_tools_request_schema(compositor, compositor_client, mcp_a, mcp_b) -> None:
    """Test agent with 2 flat MCP servers attached one by one, showing schema evolution.

    This test demonstrates:
    1. Mounting mcp_a alone → schema has only tool_a
    2. Mounting both servers → schema has both tool_a and tool_b
    3. Complex Pydantic schema with:
       - Annotated fields with regex patterns
       - Field descriptions
       - Model-level descriptions
       - Nested models (NestedInfo, CategoryInfo)
    4. Full request structure with all tools/schemas visible to the LLM
    """
    # Mount only mcp_a for phase 1 and capture Mounted object
    mounted_a = await compositor.mount_inproc(MCPMountPrefix("mcp_a"), mcp_a)

    @DecoratorMock.mock()
    def mock(m: DecoratorMock):
        # Phase 1: only mcp_a mounted
        req = yield
        assert req.tools is not None
        assert {"mcp_a_tool_a"} <= {t.name for t in req.tools}
        print("\nPHASE 1 REQUEST (mcp_a only):")
        print(json.dumps(req.model_dump(exclude_none=True), indent=2))

        yield m.mcp_tool_call(mounted_a.prefix, TOOL_A_NAME, ToolAInput(param_x=10, param_y=20))
        yield m.assistant_text("The result is 30.")

        # Phase 2: both servers mounted
        req = yield
        assert req.tools is not None
        assert {"mcp_a_tool_a", "mcp_b_tool_b"} <= {t.name for t in req.tools}
        print("\nPHASE 2 REQUEST (mcp_a + mcp_b):")
        print(json.dumps(req.model_dump(exclude_none=True), indent=2))

        # Detailed schema assertions
        tool_a = next(t for t in req.tools if t.name == "mcp_a_tool_a")
        assert tool_a.description == "Perform tool A on the inputs."
        assert tool_a.type == "function"
        assert tool_a.parameters["type"] == "object"
        assert tool_a.parameters["properties"]["param_x"]["type"] == "number"
        assert tool_a.parameters["properties"]["param_y"]["type"] == "number"
        assert set(tool_a.parameters["required"]) == {"param_x", "param_y"}

        tool_b = next(t for t in req.tools if t.name == "mcp_b_tool_b")
        assert "Perform tool B with complex validation" in tool_b.description
        assert tool_b.type == "function"
        params_b = tool_b.parameters
        assert params_b["type"] == "object"

        # Top-level fields
        props = params_b["properties"]
        assert props["identifier"]["type"] == "string"
        assert props["count"]["type"] == "integer"
        assert "$ref" in props["nested"]
        assert "$ref" in props["category"]
        assert props["flag"]["type"] == "boolean"
        assert set(params_b["required"]) == {"identifier", "count", "nested", "category", "flag"}

        # Nested models in $defs
        assert "$defs" in params_b
        nested_def = params_b["$defs"]["NestedInfo"]
        assert nested_def["properties"]["regex"]["pattern"] == r"^\d{5}$"
        assert nested_def["properties"]["text_defaultd"]["default"] == "DEFAULT"

        category_def = params_b["$defs"]["CategoryInfo"]
        assert set(category_def["properties"]["type"]["enum"]) == {"type_a", "type_b", "type_c"}

        print("\nMCP_A_TOOL_A SCHEMA:")
        print(json.dumps(tool_a.model_dump(exclude_none=True), indent=2))

        print("\nMCP_B_TOOL_B SCHEMA:")
        print(json.dumps(tool_b.model_dump(exclude_none=True), indent=2))

        yield m.mcp_tool_call(mounted_a.prefix, TOOL_A_NAME, ToolAInput(param_x=10, param_y=20))
        yield m.assistant_text("The result is 30.")

    system_prompt = "You are a helpful assistant. Calculate 10 + 20."

    print("PHASE 1: MCP_A ONLY")

    agent = await Agent.create(
        mcp_client=compositor_client,
        client=mock,
        handlers=[FinishOnTextMessageHandler()],
        parallel_tool_calls=False,
        tool_policy=RequireAnyTool(),
    )
    agent.process_message(SystemMessage.text(system_prompt))
    await agent.run()

    print("PHASE 2: MCP_A + MCP_B")

    # Mount mcp_b for phase 2 (mcp_a already mounted)
    await compositor.mount_inproc(MCPMountPrefix("mcp_b"), mcp_b)

    agent = await Agent.create(
        mcp_client=compositor_client,
        client=mock,
        handlers=[FinishOnTextMessageHandler()],
        parallel_tool_calls=False,
        tool_policy=RequireAnyTool(),
    )
    agent.process_message(SystemMessage.text(system_prompt))
    await agent.run()
