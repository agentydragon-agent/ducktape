"""Test agent with 2 flat tool decorator MCP servers showing full OpenAI request schema.

This test demonstrates how schemas from flat tool decorators are passed to the LLM,
including complex nested models with Annotated fields, regex patterns, and descriptions.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Final, Literal

from hamcrest import (
    assert_that,
    contains_inanyorder,
    contains_string,
    equal_to,
    has_entries,
    has_entry,
    has_key,
    has_properties,
)
from pydantic import BaseModel, ConfigDict, Field
import pytest

from adgn.agent.agent import Agent
from adgn.agent.handler import FinishOnTextMessageHandler
from adgn.agent.loop_control import RequireAnyTool
from adgn.mcp.enhanced import EnhancedFastMCP
from adgn.openai_utils.model import SystemMessage
from tests.llm.support.openai_mock import CapturingOpenAIModel
from tests.support.steps import AssistantMessage, MakeCall

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
def server_a() -> EnhancedFastMCP:
    """Create server A with a simple flat tool."""
    mcp = EnhancedFastMCP("server_a")

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
def server_b() -> EnhancedFastMCP:
    """Create server B with complex nested schema."""
    mcp = EnhancedFastMCP("server_b")

    @mcp.flat_model()
    def tool_b(input: ToolBInput) -> ToolBResult:
        """Perform tool B with complex validation.

        Processes the request with nested validation and returns
        either success or error response.
        """
        # Simple validation: check if identifier contains "invalid"
        if "invalid" in input.identifier.lower():
            return ResponseB(
                status="error",
                error_code="INVALID_IDENTIFIER",
                message=f"Identifier '{input.identifier}' is not allowed",
            )

        return ResponseA(message=f"Processed {input.identifier}")

    return mcp


async def test_agent_compositor_flat_tools_request_schema(
    responses_factory, compositor, compositor_client, server_a, server_b, make_step_runner
) -> None:
    """Test agent with 2 flat MCP servers attached one by one, showing schema evolution.

    This test demonstrates:
    1. Mounting server_a alone → schema has only tool_a
    2. Mounting both servers → schema has both tool_a and tool_b
    3. Complex Pydantic schema with:
       - Annotated fields with regex patterns
       - Field descriptions
       - Model-level descriptions
       - Nested models (NestedInfo, CategoryInfo)
    4. Full request structure with all tools/schemas visible to the LLM
    """
    print("PHASE 1: SERVER_A ONLY")

    # Mount only server_a for phase 1 and capture Mounted object
    mounted_a = await compositor.mount_inproc("server_a", server_a)

    runner_phase1 = make_step_runner(
        steps=[
            MakeCall(mounted_a.prefix, TOOL_A_NAME, ToolAInput(param_x=10, param_y=20)),
            AssistantMessage("The result is 30."),
        ]
    )
    client_phase1 = CapturingOpenAIModel(runner_phase1)

    system_prompt = "You are a helpful assistant. Calculate 10 + 20."

    # Use compositor_client fixture for phase 1
    agent = await Agent.create(
        mcp_client=compositor_client,
        client=client_phase1,
        handlers=[FinishOnTextMessageHandler()],
        parallel_tool_calls=False,
        tool_policy=RequireAnyTool(),
    )
    agent.insert_message(SystemMessage.text(system_prompt))
    await agent.run()

    # Verify phase 1
    phase1_request = client_phase1.captured[0]
    assert phase1_request.tools is not None  # Type narrowing for mypy
    # Check that server_a tool is present (resources server tools are also present)
    phase1_tool_names = {t.name for t in phase1_request.tools}
    assert "server_a_tool_a" in phase1_tool_names

    print("\nPHASE 1 REQUEST (server_a only):")
    print(json.dumps(phase1_request.model_dump(exclude_none=True), indent=2))

    print("PHASE 2: SERVER_A + SERVER_B")

    # Mount server_b for phase 2 (server_a already mounted)
    await compositor.mount_inproc("server_b", server_b)

    runner_phase2 = make_step_runner(
        steps=[
            MakeCall(mounted_a.prefix, TOOL_A_NAME, ToolAInput(param_x=10, param_y=20)),
            AssistantMessage("The result is 30."),
        ]
    )
    client_phase2 = CapturingOpenAIModel(runner_phase2)

    # Use compositor_client fixture for phase 2
    agent = await Agent.create(
        mcp_client=compositor_client,
        client=client_phase2,
        handlers=[FinishOnTextMessageHandler()],
        parallel_tool_calls=False,
        tool_policy=RequireAnyTool(),
    )
    agent.insert_message(SystemMessage.text(system_prompt))
    await agent.run()

    # Verify phase 2
    first_request = client_phase2.captured[0]
    assert first_request.tools is not None  # Type narrowing for mypy
    # Check that both server tools are present (resources server tools are also present)
    phase2_tool_names = {t.name for t in first_request.tools}
    assert "server_a_tool_a" in phase2_tool_names
    assert "server_b_tool_b" in phase2_tool_names

    print("\nPHASE 2 REQUEST (server_a + server_b):")
    print(json.dumps(first_request.model_dump(exclude_none=True), indent=2))
    print()

    # Find server_a_tool_a tool
    tool_a = next((t for t in first_request.tools if t.name == "server_a_tool_a"), None)
    assert tool_a is not None
    assert_that(tool_a, has_properties(description="Perform tool A on the inputs.", type="function"))

    # Verify server_a_tool_a schema (flat parameters)
    params_a = tool_a.parameters
    assert_that(params_a, has_entry("type", "object"))
    # Explicit Any types for nested matchers to avoid PyHamcrest type inference issues
    param_x_matcher: Any = has_entries(type="number", description="First parameter")
    param_y_matcher: Any = has_entries(type="number", description="Second parameter")
    assert_that(params_a["properties"], has_entries(param_x=param_x_matcher, param_y=param_y_matcher))
    assert_that(params_a["required"], contains_inanyorder("param_x", "param_y"))

    # Find server_b_tool_b tool
    tool_b = next((t for t in first_request.tools if t.name == "server_b_tool_b"), None)
    assert tool_b is not None
    assert_that(
        tool_b, has_properties(description=contains_string("Perform tool B with complex validation"), type="function")
    )

    # Verify server_b_tool_b schema (complex, nested)
    params_b = tool_b.parameters
    assert_that(params_b, has_entry("type", "object"))

    # Verify top-level fields exist and have correct types/descriptions
    props = params_b["properties"]
    # Explicit Any types for nested matchers to avoid PyHamcrest type inference issues
    identifier_matcher: Any = has_entries(type="string", description="Required regex field")
    count_matcher: Any = has_entries(type="integer", description="Int with range")
    nested_matcher: Any = has_key("$ref")
    category_matcher: Any = has_key("$ref")
    flag_matcher: Any = has_entries(type="boolean", default=False)
    assert_that(
        props,
        has_entries(
            identifier=identifier_matcher,
            count=count_matcher,
            nested=nested_matcher,
            category=category_matcher,
            flag=flag_matcher,
        ),
    )

    # Verify nested NestedInfo model
    # Note: nested field has no description (OpenAI strict mode - $ref fields can't have extra keywords)
    assert_that(params_b, has_key("$defs"))
    nested_def = params_b["$defs"]["NestedInfo"]
    # Explicit Any types for nested matchers to avoid PyHamcrest type inference issues
    regex_matcher: Any = has_entries(description="Regex validation", pattern=equal_to(r"^\d{5}$"), type="string")
    text_defaultd_matcher: Any = has_entries(default="DEFAULT", description="Text with default", type="string")
    assert_that(nested_def["properties"], has_entries(regex=regex_matcher, text_defaultd=text_defaultd_matcher))
    # NestedInfo required: ALL fields (OpenAI strict mode requires all fields in required array, even with defaults)
    assert_that(nested_def["required"], contains_inanyorder("regex", "text_defaultd"))

    # Verify nested CategoryInfo model (with Literal)
    category_def = params_b["$defs"]["CategoryInfo"]
    type_schema = category_def["properties"]["type"]
    assert_that(type_schema, has_key("enum"))
    assert_that(type_schema["enum"], contains_inanyorder("type_a", "type_b", "type_c"))

    # Verify required fields (OpenAI strict mode: ALL fields must be required, even with defaults)
    assert_that(params_b["required"], contains_inanyorder("identifier", "count", "nested", "category", "flag"))

    # Print tool schemas for manual inspection
    print("\n" + "=" * 80)
    print("SERVER_A_TOOL_A SCHEMA")
    print("=" * 80)
    print(json.dumps(tool_a.model_dump(exclude_none=True), indent=2))
    print("=" * 80)

    print("\n" + "=" * 80)
    print("SERVER_B_TOOL_B SCHEMA")
    print("=" * 80)
    print(json.dumps(tool_b.model_dump(exclude_none=True), indent=2))
    print("=" * 80)
