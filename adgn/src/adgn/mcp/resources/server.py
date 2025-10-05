from typing import Any, Protocol

from mcp import types as mcp_types
from pydantic import BaseModel, ConfigDict, Field

from adgn.mcp._shared.fastmcp_helpers import SafeFastMCP, mcp_flat_model


class ResourceEntry(BaseModel):
    server: str = Field(description="Origin MCP server name")
    resource: mcp_types.Resource


class ResourcesBackend(Protocol):
    """Backend expected by the resources FastMCP server.

    The backend provides transport-agnostic access to resources across servers.
    This server performs filtering and windowing.
    """

    async def list_resources(self, only: list[str] | None = None) -> list[ResourceEntry]: ...
    async def read_resource(self, server: str, uri: str) -> Any: ...


class ResourcesListArgs(BaseModel):
    server: str | None = Field(default=None, description="Filter by server name (optional)")
    uri_prefix: str | None = Field(
        default=None,
        description="Restrict to URIs starting with this prefix (optional)",
    )
    model_config = ConfigDict(extra="forbid")


class ResourcesListResult(BaseModel):
    resources: list[ResourceEntry] = Field(
        description="Aggregated resources across servers (each item includes origin server)"
    )
    model_config = ConfigDict(extra="forbid")


class ResourceWindowInfo(BaseModel):
    start_offset: int = Field(description="Start byte offset used for this window")
    max_bytes: int = Field(description="Max bytes requested for this window (0 means unbounded)")
    model_config = ConfigDict(extra="forbid")


class ResourceReadResult(BaseModel):
    window: ResourceWindowInfo = Field(description="Windowing parameters reflected back")
    parts: list[dict[str, Any]] = Field(
        description="Windowed parts (text/base64). For text, bytes are decoded as UTF‑8 with replacement."
    )
    total_parts: int = Field(description="Total number of parts reported by the origin server")
    model_config = ConfigDict(extra="forbid")


class ResourcesReadArgs(BaseModel):
    server: str = Field(description="Origin MCP server name that owns the resource")
    uri: str = Field(description="Resource URI as reported by the origin server's list")
    start_offset: int = Field(default=0, ge=0, description="Start byte offset for windowed reads")
    max_bytes: int = Field(default=0, ge=0, description="Max bytes to return (0 means no limit)")
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
            base = p.blob  # base64 string per MCP spec
            norm.append({"kind": "base64", "mime": p.mimeType, "raw_str": str(base)})
            continue
        raise TypeError(f"Unsupported resource content type: {type(p).__name__}")
    return norm


def _iter_window_parts(
    contents: list[mcp_types.TextResourceContents | mcp_types.BlobResourceContents],
    start_offset: int,
    max_bytes: int | None,
):
    remaining: int | None = max_bytes if isinstance(max_bytes, int) and max_bytes > 0 else None
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
                if k in {"kind", "mime", "text", "base64", "total_bytes", "bytes_returned"}
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

    Summary
    - Synthetic server injected by the runtime; reserved name is ``resources``.
    - Provides a uniform API to discover and read resources exposed by other servers.

    Tools
    - ``list(server?: string, uri_prefix?: string) -> { resources: [...] }``
      Server-side filters by server name and URI prefix.
    - ``read(server: string, uri: string, start_offset?: int = 0, max_bytes?: int)``
      Returns a windowed payload for large text/base64 resources.

    Window semantics
    - Windowing is byte-based across the concatenation of all parts reported by the
      underlying server. Text is sliced by UTF-8 bytes and decoded with
      ``errors="replace"`` if a multi-byte character is split at the boundary.
    - Base64 parts are sliced as base64 text; decoding is the caller's responsibility.

    Capability gating
    - Only servers that advertise ``initialize.capabilities.resources`` are queried
      by the backend (see ``McpManager.list_resources``).

    Backend contract
    - ``backend`` must implement ``list_resources()`` and ``read_resource()``; the
      latter must return a typed ``ReadResourceResult`` from the python SDK.
    """
    mcp = SafeFastMCP(
        name,
        instructions=(
            "Resources aggregator. Use these tools to discover and read resources "
            "exposed by attached MCP servers.\n\n"
            "Tools:\n"
            "- list(server?: string, uri_prefix?: string) → { resources: [...] }\n"
            "  • Discover resources across servers.\n"
            "  • Filter by a single server name and/or a URI prefix.\n"
            "- read(server: string, uri: string, start_offset?: int = 0, max_bytes?: int = 0)\n"
            "  • Read a window of the resource. Text is sliced by UTF‑8 bytes and decoded with replacement.\n"
            "  • Base64 blobs are returned as base64 text; decode on the client if needed.\n\n"
            "Guidance:\n"
            "- Prefer windowed reads for large content (16–64 KiB).\n"
            "- To continue, call read again with start_offset advanced by the bytes returned.\n"
            "- Always qualify reads with the origin 'server' and the exact 'uri' from list().\n"
        ),
    )

    @mcp_flat_model(
        mcp,
        name="list",
        title="List resources",
        description=(
            "List MCP resources with optional filtering. Returns an aggregated list; "
            "each item includes the origin server name and the resource descriptor."
        ),
        structured_output=True,
    )
    async def list_resources_tool(input: ResourcesListArgs) -> ResourcesListResult:
        items = await backend.list_resources(only=[input.server] if input.server else None)
        if input.uri_prefix:
            items = [
                it
                for it in items
                if it.resource.uri and str(it.resource.uri).startswith(input.uri_prefix)
            ]
        return ResourcesListResult(resources=items)

    @mcp_flat_model(
        mcp,
        title="Read resource",
        description=(
            "Read a resource with optional windowing. Text parts are returned as UTF‑8 strings; "
            "base64 parts are returned as base64 text."
        ),
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
