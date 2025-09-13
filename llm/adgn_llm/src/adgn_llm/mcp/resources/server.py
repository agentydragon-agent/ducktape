from __future__ import annotations

from typing import Any, Protocol

from mcp.server.fastmcp import FastMCP
from mcp import types as mcp_types

# Exact SDK types for isinstance checks
ReadResourceResult = mcp_types.ReadResourceResult
TextResourceContents = mcp_types.TextResourceContents
BlobResourceContents = mcp_types.BlobResourceContents


class ResourcesBackend(Protocol):
    async def list_resources(self, only: list[str] | None = None) -> list[dict[str, Any]]: ...
    async def read_resource(self, server: str, uri: str) -> Any: ...


def make_resources_server(backend: ResourcesBackend, name: str = "resources") -> FastMCP:
    """Create a lightweight MCP server that aggregates resources across servers.

    Exposes two tools:
      - list(server?: string, uri_prefix?: string) -> { resources: [...] }
      - read(server: string, uri: string, start_offset?: int = 0, max_bytes: int) -> windowed payload

    Backend is supplied directly as an argument (e.g., McpManager).
    """
    mcp = FastMCP(name, instructions="Aggregates MCP resources and provides read with windowing")

    @mcp.tool()
    async def list_resources(server: str | None = None, uri_prefix: str | None = None) -> dict[str, Any]:
        items = await backend.list_resources(only=[server] if server else None)
        if uri_prefix:
            items = [it for it in items if isinstance(it.get("uri"), str) and it["uri"].startswith(uri_prefix)]
        return {"resources": items}

    @mcp.tool()
    async def read(
        server: str,
        uri: str,
        start_offset: int = 0,
        max_bytes: int = 0,
    ) -> dict[str, Any]:
        res = await backend.read_resource(server, uri)
        if not isinstance(res, ReadResourceResult):
            return {
                "ok": False,
                "error": f"Unexpected read_resource result type: {type(res)!r}",
            }
        contents = res.contents or []
        remaining = max(0, int(max_bytes))
        cursor = 0
        parts_out: list[dict[str, Any]] = []
        for p in contents:
            if getattr(p, "text", None) is not None:
                text_val = getattr(p, "text") or ""
                raw = text_val.encode("utf-8")
                total_len = len(raw)
                if remaining > 0:
                    start_in_part = max(0, start_offset - cursor)
                    take = max(0, min(remaining, total_len - start_in_part))
                    if take > 0:
                        chunk = raw[start_in_part : start_in_part + take]
                        parts_out.append(
                            {
                                "mime": p.mimeType,
                                "text": chunk.decode("utf-8", errors="replace"),
                                "total_bytes": total_len,
                                "bytes_returned": take,
                            }
                        )
                        remaining -= take
            elif isinstance(p, BlobResourceContents) and p.blob is not None:
                base = p.blob  # base64 string
                total_len = len(base)
                if remaining > 0:
                    start_in_part = max(0, start_offset - cursor)
                    take = max(0, min(remaining, total_len - start_in_part))
                    if take > 0:
                        parts_out.append(
                            {
                                "mime": p.mimeType,
                                "base64": base[start_in_part : start_in_part + take],
                                "total_bytes": total_len,
                                "bytes_returned": take,
                            }
                        )
                        remaining -= take
            cursor += (
                len(p.text.encode("utf-8"))
                if isinstance(p, TextResourceContents) and p.text is not None
                else (len(p.blob) if isinstance(p, BlobResourceContents) and p.blob is not None else 0)
            )
            if remaining <= 0 and max_bytes > 0:
                break

        return {
            "window": {"start_offset": start_offset, "max_bytes": max_bytes},
            "parts": parts_out,
            "total_parts": len(contents),
        }

    return mcp
