"""Direct tool provider for in-container agents without MCP overhead.

Wraps Python callables directly, avoiding MCP protocol overhead.

Usage:
    provider = DirectToolProvider()

    @provider.tool
    async def my_tool(args: MyArgsModel) -> ToolResult:
        '''Tool description from docstring.'''
        return ToolResult.text(f"Result: {args.value}")

    # Sync functions supported; can return str (auto-converted to ToolResult.text)
    @provider.tool
    def sync_tool(args: OtherArgsModel) -> str:
        '''Another tool.'''
        return "done"

    # Override tool name (useful when function name would shadow imports)
    @provider.tool(name="search")
    def search_impl(args: SearchArgs) -> ToolResult:
        '''Search for items.'''
        return ToolResult.text("found")

    agent = await Agent.create(tool_provider=provider, ...)
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, get_type_hints, overload

from pydantic import BaseModel

from agent_core.tool_provider import ToolResult, ToolSchema
from openai_utils.json_schema import OpenAICompatibleSchema

# Tool functions can return ToolResult, str, or awaitables of either
ToolReturn = ToolResult | str
ToolFn = Callable[[Any], ToolReturn | Awaitable[ToolReturn]]


@dataclass(slots=True)
class RegisteredTool:
    """A registered tool with its metadata and implementation."""

    name: str
    description: str
    parameters: type[BaseModel]
    fn: ToolFn


class DirectToolProvider:
    """Tool provider that wraps Python callables directly.

    No MCP overhead - tools are registered via decorator. Tools can return
    ToolResult or str (auto-converted to ToolResult.text).
    """

    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    @overload
    def tool(self, fn: ToolFn) -> ToolFn: ...

    @overload
    def tool(self, *, name: str) -> Callable[[ToolFn], ToolFn]: ...

    def tool(
        self,
        fn: ToolFn | None = None,
        *,
        name: str | None = None,
    ) -> ToolFn | Callable[[ToolFn], ToolFn]:
        """Decorator to register a function as a tool.

        The function must:
        - Take a single Pydantic model argument
        - Return ToolResult or str (sync or async)
        - Have a docstring (used as tool description)

        Args:
            name: Override tool name (defaults to function name)
        """

        def register(func: ToolFn) -> ToolFn:
            tool_name = name if name is not None else func.__name__
            description = inspect.getdoc(func) or ""

            # Get the parameter type from type hints
            hints = get_type_hints(func)
            sig = inspect.signature(func)
            params = list(sig.parameters.values())
            if not params:
                raise TypeError(f"Tool {tool_name} must have at least one parameter (Pydantic model for args)")

            first_param = params[0]
            param_type = hints.get(first_param.name)
            if param_type is None:
                raise TypeError(f"Tool {tool_name} parameter '{first_param.name}' must have a type annotation")
            if not (isinstance(param_type, type) and issubclass(param_type, BaseModel)):
                raise TypeError(
                    f"Tool {tool_name} parameter '{first_param.name}' must be a Pydantic BaseModel, got {param_type}"
                )

            self._tools[tool_name] = RegisteredTool(
                name=tool_name,
                description=description,
                parameters=param_type,
                fn=func,
            )
            return func

        # Handle both @provider.tool and @provider.tool(name="...")
        if fn is not None:
            return register(fn)
        return register

    async def list_tools(self) -> list[ToolSchema]:
        """Return available tools."""
        return [
            ToolSchema(
                name=t.name,
                description=t.description,
                input_schema=t.parameters.model_json_schema(schema_generator=OpenAICompatibleSchema),
            )
            for t in self._tools.values()
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Execute a tool and return the result."""
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult.error(f"Unknown tool: {name}")

        try:
            validated_args = tool.parameters.model_validate(arguments)
            result = tool.fn(validated_args)
            if isinstance(result, Awaitable):
                result = await result
            if isinstance(result, str):
                return ToolResult.text(result)
            return result
        except Exception as e:
            return ToolResult.error(f"Tool error: {e}")
