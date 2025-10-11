from __future__ import annotations

from typing import Any

from fastmcp.client.client import CallToolResult as FMCallToolResult
from mcp import types as mcp_types
from pydantic import BaseModel, TypeAdapter


def _normalize_structured_content(sc: Any) -> Any:
    """Return JSON-serializable structured content.

    - If sc is a Pydantic model, dump with mode="json".
    - Otherwise return as-is (assumed JSON-serializable already).
    """
    if isinstance(sc, BaseModel):
        return sc.model_dump(mode="json")
    return sc


def as_minimal_json(res: FMCallToolResult) -> dict[str, Any]:
    """Serialize a FastMCP CallToolResult to a compact JSON dict.

    Fields:
    - structured_content: JSON-serializable structured payload (when present)
    - is_error: bool
    Content blocks are not included here; use typed conversion if needed.
    """
    payload: dict[str, Any] = {"is_error": bool(res.is_error)}
    if res.structured_content is not None:
        payload["structured_content"] = _normalize_structured_content(res.structured_content)
    return payload


def to_pydantic(res: FMCallToolResult) -> mcp_types.CallToolResult:
    """Convert a FastMCP CallToolResult to mcp.types.CallToolResult.

    Builds a minimal payload with alias field names (structuredContent, isError).
    Content blocks are omitted by default; extend if a use case requires them.
    """
    payload: dict[str, Any] = {"isError": bool(res.is_error)}
    if res.structured_content is not None:
        payload["structuredContent"] = _normalize_structured_content(res.structured_content)
    # Always include content; preserve blocks as-is when they are already
    # Pydantic MCP content models. Otherwise, forward JSON-serializable values.
    items: list[Any] = []
    for block in res.content or []:
        if isinstance(block, BaseModel):
            items.append(block)
        else:
            items.append(block)
    payload["content"] = items
    # Validate into the Pydantic type (uses alias names)
    return TypeAdapter(mcp_types.CallToolResult).validate_python(payload)
