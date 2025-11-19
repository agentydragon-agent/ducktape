from __future__ import annotations

from typing import Any

from fastmcp.client.client import CallToolResult as FMCallToolResult
from mcp import types as mcp_types
from pydantic import TypeAdapter


def _normalize_structured_content(sc: Any) -> Any:
    """Return JSON-serializable structured content.

    Keep BaseModel instances intact so downstream typed adapters can consume them.
    """
    return sc


def serialize_tool_result_compact(res: FMCallToolResult | mcp_types.CallToolResult) -> dict[str, Any]:
    """Serialize a tool result to a compact JSON dict (structured content + flags).

    Uses MCP field names (camelCase: isError, structuredContent) as produced by mcp.types.CallToolResult.
    """
    if isinstance(res, FMCallToolResult):
        res = convert_fastmcp_result(res)

    if not isinstance(res, mcp_types.CallToolResult):  # pragma: no cover - defensive
        raise TypeError(f"Expected CallToolResult, got {type(res).__name__}")

    data = res.model_dump(mode="json", by_alias=False)
    payload: dict[str, Any] = {"is_error": data["isError"]}
    if "structuredContent" in data:
        payload["structured_content"] = data["structuredContent"]
    if content := data.get("content"):
        payload["content"] = content
    return payload


def convert_fastmcp_result(res: FMCallToolResult) -> mcp_types.CallToolResult:
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
    return TypeAdapter(mcp_types.CallToolResult).validate_python(payload)
