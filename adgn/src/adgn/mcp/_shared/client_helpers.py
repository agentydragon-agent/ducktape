from __future__ import annotations

from collections.abc import Iterable
import json

from fastmcp.client import Client
from fastmcp.exceptions import ToolError
from mcp import types as mcp_types

from adgn.mcp._shared.calltool import to_pydantic


def extract_text_blocks(contents: Iterable[mcp_types.ContentBlock]) -> list[str]:
    return [
        block.text
        for block in contents
        if isinstance(block, mcp_types.TextContent) and isinstance(block.text, str) and block.text
    ]


def extract_error_detail(res: mcp_types.CallToolResult) -> str | None:
    """Best-effort string representation of an MCP tool error result."""
    detail: str | None = None
    try:
        sc = res.structuredContent
        if isinstance(sc, dict) and sc:
            for key in ("message", "reason", "error", "detail"):
                val = sc.get(key)
                if isinstance(val, str) and val:
                    detail = val
                    break
            if detail is None:
                detail = json.dumps(sc, ensure_ascii=False)[:200]
        if not detail:
            texts = extract_text_blocks(res.content or [])
            if texts:
                detail = " | ".join(texts)[:200]
    except Exception:
        detail = None
    return detail


async def call_simple_ok(client: Client, *, name: str, arguments: dict) -> None:
    """Call a simple tool and ensure it did not error.

    - Invokes the tool via Client.call_tool to propagate ToolError directly
    - Requires a typed CallToolResult with isError == False
    - Raises RuntimeError with a readable operation name on failure
    """
    try:
        # client.call_tool preserves fastmcp.exceptions.ToolError, which is necessary
        # for tests that assert reserved policy errors bubble through untouched.
        res = await client.call_tool(name=name, arguments=arguments, raise_on_error=True)
    except ToolError:
        raise
    except Exception as exc:
        raise RuntimeError(f"{name} failed: {exc}") from exc
    if bool(res.is_error):
        detail = extract_error_detail(to_pydantic(res))
        if detail:
            raise RuntimeError(f"{name} failed: {detail}")
        raise RuntimeError(f"{name} failed")
