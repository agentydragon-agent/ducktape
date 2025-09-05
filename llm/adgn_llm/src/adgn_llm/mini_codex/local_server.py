from __future__ import annotations

from abc import ABC
from collections.abc import Callable, Mapping
from typing import Any

ToolDef = tuple[str, Mapping[str, Any], Callable[[dict[str, Any]], Any]]

# ---- Generic decorator for local servers: co-locate tool schema with impl ----


def tool(
    description: str, parameters: Mapping[str, Any],
) -> Callable[
    [Callable[[dict[str, Any]], dict[str, Any]]],
    Callable[[dict[str, Any]], dict[str, Any]],
]:
    """Annotate a method as a tool with schema and description.

    Tool name is inferred from the function name to keep definitions co-located and DRY.

    Usage:
      @tool("Get file info", {"type":"object","properties":{}})
      def read_info(self, args: dict[str, Any]) -> dict[str, Any]: ...
    """

    def _wrap(fn: Callable[[dict[str, Any]], dict[str, Any]]):  # type: ignore[type-arg]
        # Attach metadata attributes for discovery (introspection-based registry)
        fn._adgn_tool_name = fn.__name__  # type: ignore[attr-defined]
        fn._adgn_tool_desc = description  # type: ignore[attr-defined]
        fn._adgn_tool_schema = dict(parameters)  # type: ignore[attr-defined]
        return fn

    return _wrap


class LocalServer(ABC):
    """Base for in-process MCP-like servers.

    Subclasses can either:
      - Use @tool on methods and rely on default get_tools() discovery, or
      - Override get_tools() for full control.
    """

    def __init__(self, name: str):
        self.name = name

    def get_tools(self) -> dict[str, ToolDef]:
        """Default registry via @tool-decorated methods."""
        registry: dict[str, ToolDef] = {}
        for attr in dir(self):
            fn = getattr(self, attr)
            name = getattr(fn, "_adgn_tool_name", None)
            if not name:
                continue
            desc = getattr(fn, "_adgn_tool_desc", "")
            schema = getattr(
                fn, "_adgn_tool_schema", {"type": "object", "properties": {}},
            )
            registry[name] = (desc, schema, fn)
        return registry

    async def close(self) -> None:
        return None
