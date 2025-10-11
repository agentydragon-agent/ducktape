from __future__ import annotations

import json

from fastmcp.client import Client
from mcp import types as mcp_types


async def call_simple_ok(client: Client, *, name: str, arguments: dict) -> None:
    """Call a simple tool and ensure it did not error.

    - Invokes the tool via FastMCP Client.session.call_tool
    - Requires a typed CallToolResult with isError == False
    - Raises RuntimeError with a readable operation name on failure
    """
    res = await client.session.call_tool(name=name, arguments=arguments)
    if not isinstance(res, mcp_types.CallToolResult):
        raise RuntimeError(f"{name} failed: unexpected result type")
    if bool(res.isError):
        # Try to project useful error details from structuredContent or text parts
        detail: str | None = None
        try:
            sc = getattr(res, "structuredContent", None)
            if isinstance(sc, dict) and sc:
                # Prefer common keys when present
                for key in ("message", "reason", "error", "detail"):
                    val = sc.get(key)
                    if isinstance(val, str) and val:
                        detail = val
                        break
                if detail is None:
                    # Fallback to compact JSON of structured content
                    detail = json.dumps(sc, ensure_ascii=False)[:200]
            if not detail:
                parts = list(getattr(res, "content", []) or [])
                texts: list[str] = []
                for p in parts:
                    t = getattr(p, "text", None)
                    if isinstance(t, str) and t:
                        texts.append(t)
                if texts:
                    detail = " | ".join(texts)[:200]
        except Exception:
            # Best-effort only; ignore extraction failures
            detail = None
        if detail:
            raise RuntimeError(f"{name} failed: {detail}")
        raise RuntimeError(f"{name} failed")
