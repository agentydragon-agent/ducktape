from __future__ import annotations

from typing import Any

from fastmcp.client.client import CallToolResult as FMCallToolResult
from mcp import types as mcp_types
from pydantic import JsonValue, TypeAdapter


def _normalize_structured_content(sc: JsonValue) -> JsonValue:
    """Return JSON-serializable structured content.

    Keep BaseModel instances intact so downstream typed adapters can consume them.
    """
    return sc


def as_minimal_json(res: FMCallToolResult | mcp_types.CallToolResult) -> dict[str, Any]:
    """Serialize a tool result to a compact JSON dict (structured content + flags).

    Returns a dict with camelCase keys matching MCP CallToolResult field names,
    so the result can be deserialized as a valid CallToolResult.
    """
    if isinstance(res, FMCallToolResult):
        res = fastmcp_to_mcp_result(res)

    if not isinstance(res, mcp_types.CallToolResult):  # pragma: no cover - defensive
        raise TypeError(f"Expected CallToolResult, got {type(res).__name__}")

    data = res.model_dump(mode="json", by_alias=False)
    # Use camelCase keys to match MCP CallToolResult field names for deserialization
    payload: dict[str, Any] = {"isError": data.get("isError", False)}
    if "structuredContent" in data:
        payload["structuredContent"] = data["structuredContent"]
    if content := data.get("content"):
        payload["content"] = content
    return payload


def fastmcp_to_mcp_result(res: FMCallToolResult) -> mcp_types.CallToolResult:
    """Convert a FastMCP CallToolResult to mcp.types.CallToolResult.

    Builds a minimal payload with alias field names (structuredContent, isError).
    Content blocks are omitted by default; extend if a use case requires them.
    """
    payload: dict[str, Any] = {"isError": bool(res.is_error)}
    if res.structured_content is not None:
        payload["structuredContent"] = _normalize_structured_content(res.structured_content)
    # Always include content; preserve blocks as-is when they are already
    # Pydantic MCP content models. Otherwise, forward JSON-serializable values.
    payload["content"] = list(res.content or [])
    # Validate into the Pydantic type (uses alias names)
    return mcp_types.CallToolResult.model_validate(payload)


def extract_structured_content[T](result: mcp_types.CallToolResult | FMCallToolResult, output_type: type[T]) -> T:
    """Extract and parse structured content from an MCP CallToolResult.

    Handles both FastMCP client results and Pydantic MCP types.

    Args:
        result: MCP tool result (FastMCP or Pydantic variant)
        output_type: Pydantic model class or type to validate structured content as

    Returns:
        Parsed and validated instance of output_type

    Raises:
        ValueError: If structured content is missing or result is an error
        ValidationError: If structured content doesn't match output_type schema
    """
    # Normalize to Pydantic type if needed
    if isinstance(result, FMCallToolResult):
        result = fastmcp_to_mcp_result(result)

    # Direct attribute access on Pydantic model
    # Pydantic models expose both the alias (isError) and Python name (is_error)
    if result.isError:
        raise ValueError(f"Cannot extract from error result: {result}")

    # Access structured content via Pydantic alias (preferred for MCP types)
    sc = result.structuredContent
    if sc is None:
        raise ValueError(f"CallToolResult missing structured content: {result}")

    return TypeAdapter(output_type).validate_python(sc)
