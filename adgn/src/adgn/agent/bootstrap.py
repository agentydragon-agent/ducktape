"""Bootstrap handlers for injecting synthetic function calls before agent sampling.

Bootstrap handlers inject pre-determined function calls (e.g., reading resources,
listing files) before the agent's first sampling cycle. This provides context
without requiring the agent to explicitly request it.
"""

from __future__ import annotations

from contextlib import suppress
import json
from typing import TYPE_CHECKING

from pydantic import BaseModel

from adgn.mcp._shared.constants import RUNTIME_EXEC_TOOL_NAME
from adgn.mcp._shared.naming import build_mcp_function
from adgn.mcp.exec.models import ExecInput
from adgn.mcp.resources.server import ResourcesReadArgs
from adgn.mcp.stubs.typed_stubs import _resolve_output_type
from adgn.openai_utils.model import FunctionCallItem

if TYPE_CHECKING:
    from fastmcp.server import FastMCP


def introspect_server_models(server: FastMCP) -> dict[str, tuple[type[BaseModel] | None, type]]:
    """Extract tool Input/Output models from FastMCP server (no session needed).

    Returns:
        Dict mapping tool names to (Input model | None, Output type) tuples
    """
    try:
        tm = server._tool_manager  # type: ignore[attr-defined]
    except AttributeError as exc:
        raise RuntimeError("Server does not expose _tool_manager") from exc

    try:
        tools_by_name = tm._tools  # type: ignore[attr-defined]
    except AttributeError as exc:
        raise RuntimeError("Server tool manager does not expose _tools") from exc

    models: dict[str, tuple[type[BaseModel] | None, type]] = {}

    for t in tools_by_name.values():
        try:
            fm = t.fn_metadata  # type: ignore[attr-defined]
        except AttributeError:
            fm = None
        try:
            fn = t.fn  # type: ignore[attr-defined]
        except AttributeError:
            fn = None

        hinted_input = None
        hinted_output = None
        if fn is not None:
            with suppress(AttributeError):
                hinted_input = fn._mcp_flat_input_model  # type: ignore[attr-defined]
            with suppress(AttributeError):
                hinted_output = fn._mcp_flat_output_model  # type: ignore[attr-defined]

        if fm is None:
            arg_model = hinted_input
            out_model = hinted_output
            if not (isinstance(arg_model, type) and issubclass(arg_model, BaseModel)):
                continue
        else:
            arg_model = fm.arg_model  # type: ignore[attr-defined]
            out_model = fm.output_model  # type: ignore[attr-defined]
            if out_model is None or arg_model is None:
                continue

        if isinstance(hinted_input, type) and issubclass(hinted_input, BaseModel):
            input_type: type[BaseModel] | None = hinted_input
        elif isinstance(arg_model, type) and issubclass(arg_model, BaseModel):
            input_type = arg_model
        else:
            input_type = None

        try:
            tool_key = t.key  # type: ignore[attr-defined]
        except AttributeError:
            try:
                tool_key = t.name  # type: ignore[attr-defined]
            except AttributeError:
                continue

        if not isinstance(tool_key, str) or not tool_key:
            continue

        output_type = _resolve_output_type(hinted_output, out_model)
        models[tool_key] = (input_type, output_type)

    return models


class TypedBootstrapBuilder:
    """Type-safe builder for bootstrap function call items.

    Constructs FunctionCallItem instances with automatic call_id generation
    and optional type validation against introspected server schemas.

    Usage:
        # Without introspection (no type checking):
        builder = TypedBootstrapBuilder()
        call = builder.call("my_server", "my_tool", MyInput(...))

        # With introspection (validates payload types):
        builder = TypedBootstrapBuilder.for_server(server)
        call = builder.call("my_server", "my_tool", MyInput(...))  # type-checked
    """

    def __init__(self, *, call_id_prefix: str = "bootstrap") -> None:
        self._prefix = call_id_prefix
        self._counter = 0
        self._models: dict[str, tuple[type[BaseModel] | None, type]] = {}

    def next_call_id(self) -> str:
        """Generate next auto-incremented call_id."""
        self._counter += 1
        return f"{self._prefix}:{self._counter}"

    def call(self, server: str, tool: str, payload: BaseModel, *, call_id: str | None = None) -> FunctionCallItem:
        """Create a typed MCP tool call item.

        Args:
            server: MCP server name
            tool: Tool name on the server
            payload: Pydantic model instance with call arguments
            call_id: Optional explicit call_id (auto-generated if not provided)

        Returns:
            FunctionCallItem ready for bootstrap injection

        Raises:
            TypeError: If payload type doesn't match introspected Input model
        """
        # Validate payload type if we have introspection data
        tool_key = build_mcp_function(server, tool)
        if tool_key in self._models:
            expected_input, _ = self._models[tool_key]
            if expected_input is not None and not isinstance(payload, expected_input):
                raise TypeError(f"{server}/{tool} expects {expected_input.__name__}, got {type(payload).__name__}")

        return FunctionCallItem(
            call_id=call_id or self.next_call_id(),
            name=build_mcp_function(server, tool),
            arguments=json.dumps(payload.model_dump(exclude_none=True)),
        )

    @classmethod
    def for_server(cls, server: FastMCP, *, call_id_prefix: str = "bootstrap") -> TypedBootstrapBuilder:
        """Create builder with introspected tool schemas from FastMCP server.

        No MCP session required - only introspects the server's tool registry.

        Args:
            server: FastMCP server instance to introspect
            call_id_prefix: Prefix for auto-generated call_ids

        Returns:
            Builder with type validation enabled for the server's tools
        """
        builder = cls(call_id_prefix=call_id_prefix)
        builder._models = introspect_server_models(server)
        return builder


# Helper functions for common bootstrap patterns


def read_resource_call(
    builder: TypedBootstrapBuilder, server: str, uri: str, *, max_bytes: int = 65536
) -> FunctionCallItem:
    """Create a resources.read bootstrap call.

    Args:
        builder: TypedBootstrapBuilder instance
        server: MCP server name that owns the resource
        uri: Resource URI (e.g., "resource://prompt_eval/po_run_id")
        max_bytes: Maximum bytes to read (default: 64KB)

    Returns:
        FunctionCallItem for resources.read call
    """
    return builder.call(
        "resources", "read", ResourcesReadArgs(server=server, uri=uri, start_offset=0, max_bytes=max_bytes)
    )


def docker_exec_call(
    builder: TypedBootstrapBuilder, server: str, cmd: list[str], *, timeout_ms: int = 10_000
) -> FunctionCallItem:
    """Create a docker_exec bootstrap call.

    Args:
        builder: TypedBootstrapBuilder instance
        server: MCP server name (e.g., "runtime")
        cmd: Command and arguments to execute
        timeout_ms: Timeout in milliseconds (default: 10s)

    Returns:
        FunctionCallItem for docker_exec call
    """
    return builder.call(server, RUNTIME_EXEC_TOOL_NAME, ExecInput(cmd=cmd, timeout_ms=timeout_ms))


# TODO: Add more helper functions for common patterns as needed (git_diff_call, etc.)
# Scope these appropriately (e.g., in conftest for tests, per-module for specific domains)
# Do not pollute global scope with domain-specific helpers
