"""Direct tool provider for in-container agents without MCP overhead.

Wraps Python callables directly, avoiding MCP protocol overhead.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from agent_core.tool_provider import TextContent, ToolResult, ToolSchema
from openai_utils.json_schema import OpenAICompatibleSchema


@dataclass
class Tool:
    """A tool that can be called by the agent.

    Args:
        name: Tool name (must match what LLM calls)
        description: Description shown to LLM
        parameters: Pydantic model class for argument validation
        fn: Async function that takes validated args and returns ToolResult
    """

    name: str
    description: str
    parameters: type[BaseModel]
    fn: Callable[[BaseModel], Awaitable[ToolResult]]


class DirectToolProvider:
    """Tool provider that wraps Python callables directly.

    No MCP overhead - tools are registered as async functions.
    """

    def __init__(self, tools: list[Tool]) -> None:
        self._tools = tools
        self._tool_map = {t.name: t for t in tools}

    async def list_tools(self) -> list[ToolSchema]:
        """Return available tools."""
        return [
            ToolSchema(
                name=t.name,
                description=t.description,
                input_schema=t.parameters.model_json_schema(schema_generator=OpenAICompatibleSchema),
            )
            for t in self._tools
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Execute a tool and return the result."""
        tool = self._tool_map.get(name)
        if tool is None:
            return ToolResult(content=[TextContent(text=f"Unknown tool: {name}")], is_error=True)

        try:
            validated_args = tool.parameters.model_validate(arguments)
            return await tool.fn(validated_args)
        except Exception as e:
            return ToolResult(content=[TextContent(text=f"Tool error: {e}")], is_error=True)
