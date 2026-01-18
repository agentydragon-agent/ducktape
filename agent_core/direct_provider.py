"""Direct tool provider for in-container agents without MCP overhead.

Wraps Python callables directly, avoiding MCP protocol overhead.

Usage:
    provider = DirectToolProvider()

    @provider.tool
    async def my_tool(args: MyArgsModel) -> ToolResult:
        '''Tool description from docstring.'''
        return ToolResult.text(f"Result: {args.value}")

    # Sync functions also supported
    @provider.tool
    def sync_tool(args: OtherArgsModel) -> ToolResult:
        '''Another tool.'''
        return ToolResult.text("done")

    # Override tool name (useful when function name would shadow imports)
    @provider.tool(name="search")
    def search_impl(args: SearchArgs) -> ToolResult:
        '''Search for items.'''
        return ToolResult.text("found")

    agent = await Agent.create(tool_provider=provider, ...)
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import Any, ParamSpec, TypeVar, get_type_hints, overload

from pydantic import BaseModel

from agent_core.tool_provider import TextContent, ToolResult, ToolSchema
from openai_utils.json_schema import OpenAICompatibleSchema

P = ParamSpec("P")
T = TypeVar("T")


class DirectToolProvider:
    """Tool provider that wraps Python callables directly.

    No MCP overhead - tools are registered via decorator.

    Example:
        provider = DirectToolProvider()

        @provider.tool
        async def search(args: SearchArgs) -> ToolResult:
            '''Search for files matching pattern.'''
            ...

        @provider.tool
        def list_files(args: ListFilesArgs) -> ToolResult:
            '''List files in directory.'''
            ...
    """

    def __init__(self) -> None:
        self._tools: dict[str, _RegisteredTool] = {}

    @overload
    def tool(self, fn: Callable[[Any], ToolResult]) -> Callable[[Any], ToolResult]: ...

    @overload
    def tool(self, fn: Callable[[Any], Awaitable[ToolResult]]) -> Callable[[Any], Awaitable[ToolResult]]: ...

    @overload
    def tool(
        self, *, name: str
    ) -> Callable[
        [Callable[[Any], ToolResult] | Callable[[Any], Awaitable[ToolResult]]],
        Callable[[Any], ToolResult] | Callable[[Any], Awaitable[ToolResult]],
    ]: ...

    def tool(
        self,
        fn: Callable[[Any], ToolResult] | Callable[[Any], Awaitable[ToolResult]] | None = None,
        *,
        name: str | None = None,
    ) -> (
        Callable[[Any], ToolResult]
        | Callable[[Any], Awaitable[ToolResult]]
        | Callable[
            [Callable[[Any], ToolResult] | Callable[[Any], Awaitable[ToolResult]]],
            Callable[[Any], ToolResult] | Callable[[Any], Awaitable[ToolResult]],
        ]
    ):
        """Decorator to register a function as a tool.

        The function must:
        - Take a single Pydantic model argument
        - Return ToolResult (sync or async)
        - Have a docstring (used as tool description)

        Args:
            name: Override tool name (defaults to function name)

        Example:
            @provider.tool
            async def my_tool(args: MyArgsModel) -> ToolResult:
                '''Description shown to LLM.'''
                return ToolResult.text("result")

            @provider.tool(name="custom_name")
            def impl(args: ArgsModel) -> ToolResult:
                '''Description.'''
                return ToolResult.text("done")
        """

        def register(
            func: Callable[[Any], ToolResult] | Callable[[Any], Awaitable[ToolResult]],
        ) -> Callable[[Any], ToolResult] | Callable[[Any], Awaitable[ToolResult]]:
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

            is_async = asyncio.iscoroutinefunction(func)
            self._tools[tool_name] = _RegisteredTool(
                name=tool_name,
                description=description,
                parameters=param_type,
                fn=func,
                is_async=is_async,
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
            return ToolResult(content=[TextContent(text=f"Unknown tool: {name}")], is_error=True)

        try:
            validated_args = tool.parameters.model_validate(arguments)
            if tool.is_async:
                return await tool.fn(validated_args)
            else:
                return tool.fn(validated_args)
        except Exception as e:
            return ToolResult(content=[TextContent(text=f"Tool error: {e}")], is_error=True)


class _RegisteredTool:
    """Internal representation of a registered tool."""

    __slots__ = ("name", "description", "parameters", "fn", "is_async")

    def __init__(
        self,
        name: str,
        description: str,
        parameters: type[BaseModel],
        fn: Callable[[Any], ToolResult] | Callable[[Any], Awaitable[ToolResult]],
        is_async: bool,
    ) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters
        self.fn = fn
        self.is_async = is_async
