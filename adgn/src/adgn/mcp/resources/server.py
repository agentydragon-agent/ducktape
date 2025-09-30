from typing import Any, Protocol, cast

from adgn.mcp._shared.fastmcp_helpers import SafeFastMCP
from adgn.mcp._shared.fastmcp_helpers import mcp_flat_model
from pydantic import BaseModel, ConfigDict, Field
from mcp import types as mcp_types


class ResourcesBackend(Protocol):
    """Backend expected by the resources FastMCP server.

    The backend provides transport-agnostic access to resources across servers.
    This server performs filtering and windowing.
    """

    async def list_resources(
        self, only: list[str] | None = None
    ) -> list[dict[str, Any]]: ...
    async def read_resource(self, server: str, uri: str) -> Any: ...


class ResourcesListArgs(BaseModel):
    server: str | None = Field(
        default=None, description="Filter by server name (optional)"
    )
    uri_prefix: str | None = Field(
        default=None,
        description="Restrict to URIs starting with this prefix (optional)",
    )
    model_config = ConfigDict(extra="forbid")


class ResourcesListResult(BaseModel):
    resources: list[dict[str, Any]]
    model_config = ConfigDict(extra="forbid")


class ResourceWindowInfo(BaseModel):
    start_offset: int
    max_bytes: int
    model_config = ConfigDict(extra="forbid")


class ResourceReadResult(BaseModel):
    window: ResourceWindowInfo
    parts: list[dict[str, Any]]
    total_parts: int
    model_config = ConfigDict(extra="forbid")


class ResourcesReadArgs(BaseModel):
    server: str
    uri: str
    start_offset: int = Field(
        default=0, ge=0, description="Start byte offset for windowed reads"
    )
    max_bytes: int = Field(
        default=0, ge=0, description="Max bytes to return (0 means no limit)"
    )
    model_config = ConfigDict(extra="forbid")


def _normalize_parts(
    contents: list[mcp_types.TextResourceContents | mcp_types.BlobResourceContents],
) -> list[dict[str, Any]]:
    """Normalize resource parts to a small internal dict shape.

    Each normalized part is a dict with keys:
      - kind: "text" | "base64"
      - mime: str | None
      - raw_bytes: bytes           (for kind=="text")
      - raw_str: str               (for kind=="base64")
    """
    norm: list[dict[str, Any]] = []
    for p in contents or []:
        if isinstance(p, mcp_types.TextResourceContents):
            norm.append(
                {
                    "kind": "text",
                    "mime": p.mimeType,
                    "raw_bytes": p.text.encode("utf-8"),
                }
            )
            continue
        if isinstance(p, mcp_types.BlobResourceContents):
            base = p.data  # base64 string per MCP spec
            norm.append({"kind": "base64", "mime": p.mimeType, "raw_str": str(base)})
            continue
        raise TypeError(f"Unsupported resource content type: {type(p).__name__}")
    return norm


def _iter_window_parts(
    contents: list[mcp_types.TextResourceContents | mcp_types.BlobResourceContents],
    start_offset: int,
    max_bytes: int | None,
):
    remaining: int | None = (
        max_bytes if isinstance(max_bytes, int) and max_bytes > 0 else None
    )
    cursor = 0
    for part in _normalize_parts(contents):
        mime = part.get("mime")
        if part.get("kind") == "text":
            raw: bytes = part["raw_bytes"]
            total_len = len(raw)
            if remaining is None or remaining > 0:
                start_in_part = max(0, start_offset - cursor)
                take_cap = remaining if isinstance(remaining, int) else total_len
                take = max(0, min(take_cap, total_len - start_in_part))
                if take > 0:
                    chunk = raw[start_in_part : start_in_part + take]
                    yield {
                        "kind": "text",
                        "mime": mime,
                        "text": chunk.decode("utf-8", errors="replace"),
                        "total_bytes": total_len,
                        "bytes_returned": take,
                    }
                    if remaining is not None:
                        remaining -= take
            cursor += total_len
        elif part.get("kind") == "base64":
            base: str = part["raw_str"]
            total_len = len(base)
            if remaining is None or remaining > 0:
                start_in_part = max(0, start_offset - cursor)
                take_cap = remaining if isinstance(remaining, int) else total_len
                take = max(0, min(take_cap, total_len - start_in_part))
                if take > 0:
                    yield {
                        "kind": "base64",
                        "mime": mime,
                        "base64": base[start_in_part : start_in_part + take],
                        "total_bytes": total_len,
                        "bytes_returned": take,
                    }
                    if remaining is not None:
                        remaining -= take
            cursor += total_len
        if remaining is not None and remaining <= 0:
            break


def _build_window_payload(
    contents: list[Any], start_offset: int, max_bytes: int | None
) -> ResourceReadResult:
    parts_out: list[dict[str, Any]] = []
    for part in _iter_window_parts(contents, start_offset, max_bytes):
        parts_out.append(
            {
                k: v
                for k, v in part.items()
                if k
                in {"kind", "mime", "text", "base64", "total_bytes", "bytes_returned"}
            }
        )
    return ResourceReadResult(
        window=ResourceWindowInfo(start_offset=start_offset, max_bytes=max_bytes or 0),
        parts=parts_out,
        total_parts=len(contents or []),
    )


def make_resources_server(
    backend: ResourcesBackend,
    name: str = "resources",
) -> SafeFastMCP:
    """Create a lightweight MCP server that aggregates resources across servers.

    Exposes two tools with server-side filtering and windowing:
      - list(server?: string, uri_prefix?: string) -> { resources: [...] }
      - read(server: string, uri: string, start_offset?: int = 0, max_bytes?: int) -> windowed payload

    Backend is supplied directly as an argument (e.g., McpManager).
    """
    mcp = SafeFastMCP(
        name,
        instructions="Aggregates MCP resources and provides read with windowing",
    )

    @mcp_flat_model(
        mcp,
        name="list",
        title="List resources",
        description="List MCP resources with optional filtering",
        structured_output=True,
    )
    async def list_resources_tool(input: ResourcesListArgs) -> ResourcesListResult:
        items = await backend.list_resources(
            only=[input.server] if input.server else None
        )
        if input.uri_prefix:
            items = [
                it
                for it in items
                if isinstance(it.get("uri"), str)
                and cast(str, it["uri"]).startswith(input.uri_prefix)
            ]
        return ResourcesListResult(resources=items)

    @mcp_flat_model(
        mcp,
        title="Read resource",
        description="Read a resource with optional windowing",
        structured_output=True,
    )
    async def read(input: ResourcesReadArgs) -> ResourceReadResult:
        res = await backend.read_resource(input.server, input.uri)
        # Strict: backend must return a typed ReadResourceResult
        if not isinstance(res, mcp_types.ReadResourceResult):
            raise TypeError(
                f"backend.read_resource must return ReadResourceResult, got {type(res).__name__}"
            )
        contents = res.contents or []
        return _build_window_payload(
            list(contents),
            input.start_offset,
            None if input.max_bytes == 0 else input.max_bytes,
        )

    return mcp
