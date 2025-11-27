"""Extract tool schemas from FastMCP servers for RichDisplayHandler.

Introspects tool return types from FastMCP server instances to build
schema registries for typed display rendering.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from fastmcp.server import FastMCP


def extract_tool_schemas(servers: dict[str, FastMCP]) -> dict[tuple[str, str], type[BaseModel]]:
    """Extract tool result types from FastMCP servers.

    Args:
        servers: Mapping of server_name -> FastMCP instance

    Returns:
        Mapping of (server_name, tool_name) -> Pydantic result type

    Only includes tools with Pydantic BaseModel return annotations.
    """
    schemas: dict[tuple[str, str], type[BaseModel]] = {}

    for server_name, server in servers.items():
        # Access internal tool registry (stable FastMCP API)
        try:
            tools = server._tool_manager._tools
        except AttributeError:
            continue

        for tool_name, tool in tools.items():
            # Extract return annotation from original function
            # FunctionTool.fn is not in public API but stable
            try:
                fn = tool.fn  # type: ignore[attr-defined]
            except AttributeError:
                continue

            try:
                sig = inspect.signature(fn)
            except (ValueError, TypeError):
                continue

            return_type = sig.return_annotation
            # Only register if it's a Pydantic BaseModel subclass
            if inspect.isclass(return_type) and issubclass(return_type, BaseModel):
                schemas[(server_name, tool_name)] = return_type

    return schemas


def extract_tool_input_schemas(servers: dict[str, FastMCP]) -> dict[tuple[str, str], type[BaseModel]]:
    """Extract tool input types from FastMCP servers.

    Args:
        servers: Mapping of server_name -> FastMCP instance

    Returns:
        Mapping of (server_name, tool_name) -> Pydantic input type

    Only includes tools with a single Pydantic BaseModel parameter annotation.
    Handles both regular tools and flat-model tools (with _mcp_flat_input_model).
    """
    schemas: dict[tuple[str, str], type[BaseModel]] = {}

    for server_name, server in servers.items():
        # Access internal tool registry (stable FastMCP API)
        try:
            tools = server._tool_manager._tools
        except AttributeError:
            continue

        for tool_name, tool in tools.items():
            try:
                fn = tool.fn  # type: ignore[attr-defined]
            except AttributeError:
                continue

            # Check for flat-model wrapper first
            try:
                input_model = fn._mcp_flat_input_model  # type: ignore[attr-defined]
                if inspect.isclass(input_model) and issubclass(input_model, BaseModel):
                    schemas[(server_name, tool_name)] = input_model
                continue
            except AttributeError:
                pass

            # Fall back to signature introspection for regular tools
            try:
                sig = inspect.signature(fn)
            except (ValueError, TypeError):
                continue

            params = list(sig.parameters.values())
            pydantic_params = [
                p
                for p in params
                if p.annotation != inspect.Parameter.empty
                and inspect.isclass(p.annotation)
                and issubclass(p.annotation, BaseModel)
            ]

            if len(pydantic_params) == 1:
                schemas[(server_name, tool_name)] = pydantic_params[0].annotation

    return schemas
