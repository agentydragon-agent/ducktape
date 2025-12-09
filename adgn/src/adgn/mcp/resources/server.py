import asyncio
from collections.abc import Iterator, Sequence
from enum import StrEnum
from typing import Annotated, Literal

from fastmcp.exceptions import ToolError
from fastmcp.server.server import add_resource_prefix, remove_resource_prefix
from mcp import types as mcp_types
from mcp.shared.exceptions import McpError
from pydantic import BaseModel, ConfigDict, Field

from adgn.mcp._shared.constants import RESOURCES_SUBSCRIPTIONS_INDEX_URI
from adgn.mcp._shared.resources import derive_origin_server
from adgn.mcp._shared.types import SimpleOk
from adgn.mcp._shared.urls import ANY_URL
from adgn.mcp.compositor.server import Compositor, MountEvent
from adgn.mcp.enhanced import EnhancedFastMCP
from adgn.mcp.resources.types import ListSubscriptionSummary, ResourceEntry, SubscriptionsIndex, SubscriptionSummary
from adgn.mcp.snapshots import RunningServerEntry
from adgn.openai_utils.pydantic_strict_mode import OpenAIStrictModeBaseModel

## ResourceEntry moved to adgn.mcp.resources.types to avoid cycles

# Default max bytes for resource reading operations
DEFAULT_MAX_BYTES = 25_000


class ResourcesListArgs(OpenAIStrictModeBaseModel):
    server: str | None = Field(description="Filter by server name (None = all servers)")
    uri_prefix: str | None = Field(description="Restrict to URIs starting with this prefix (None = no filter)")


class ResourcesListResult(BaseModel):
    resources: list[ResourceEntry] = Field(
        description="Aggregated resources across servers (each item includes origin server)"
    )
    model_config = ConfigDict(extra="forbid")


class ResourceTemplateEntry(BaseModel):
    server: str = Field(description="Origin MCP server name that owns this template")
    template: mcp_types.ResourceTemplate = Field(description="Resource template from origin server")
    model_config = ConfigDict(extra="forbid")


class ResourceTemplatesListResult(BaseModel):
    templates: list[ResourceTemplateEntry] = Field(
        description="Aggregated resource templates across servers (each item includes origin server)"
    )
    model_config = ConfigDict(extra="forbid")


class ResourceWindowInfo(BaseModel):
    start_offset: int = Field(description="Start byte offset used for this window")
    max_bytes: int = Field(description="Max bytes requested for this window (0 means unbounded)")
    model_config = ConfigDict(extra="forbid")


"""
Typed read result is defined after WindowedPart to avoid forward refs.
"""


class ResourcesReadArgs(OpenAIStrictModeBaseModel):
    server: str = Field(description="Origin MCP server name that owns the resource")
    uri: str = Field(description="Resource URI as reported by the origin server's list")
    start_offset: int = Field(ge=0, description="Start byte offset for windowed reads")
    max_bytes: int | None = Field(
        description=f"Max bytes to return (None means use default limit of {DEFAULT_MAX_BYTES:,} bytes)"
    )


class ResourcesSubscribeArgs(OpenAIStrictModeBaseModel):
    server: str = Field(description="Origin MCP server name")
    uri: str = Field(description="Resource URI to subscribe to")


# No compositor meta resources here; see adgn.mcp.compositor.meta_server

# ---- Top-level types for resources server (was nested) --------------------


class SubscriptionRecord(BaseModel):
    server: str
    uri: str
    pinned: bool = False
    active: bool = False
    last_error: str | None = None
    model_config = ConfigDict(extra="forbid")


class ListSubscribeArgs(OpenAIStrictModeBaseModel):
    server: str


class ResourceCapabilityFeature(StrEnum):
    SUBSCRIBE = "subscribe"
    LIST_CHANGED = "listChanged"


# ---- Internal typed representations for normalized/window parts -----------


class _MimeBase(BaseModel):
    mime: str | None = None
    model_config = ConfigDict(extra="forbid")


class TextPart(_MimeBase):
    kind: Literal["text"] = "text"
    raw_bytes: bytes


class BlobPart(_MimeBase):
    kind: Literal["base64"] = "base64"
    raw_str: str


NormalizedPart = Annotated[TextPart | BlobPart, Field(discriminator="kind")]


class _WindowedBase(_MimeBase):
    total_bytes: int
    bytes_returned: int


class WindowedTextPart(_WindowedBase):
    kind: Literal["text"] = "text"
    text: str


class WindowedBlobPart(_WindowedBase):
    kind: Literal["base64"] = "base64"
    base64: str


WindowedPart = Annotated[WindowedTextPart | WindowedBlobPart, Field(discriminator="kind")]


class ResourceReadResult(BaseModel):
    window: ResourceWindowInfo = Field(description="Windowing parameters reflected back")
    parts: list[WindowedPart] = Field(description="Windowed parts (text/base64)")
    total_parts: int = Field(description="Total number of parts reported by the origin server")
    model_config = ConfigDict(extra="forbid")


# ---- Block-level windowing types (new implementation) --------------------

BaseResourceContents = mcp_types.TextResourceContents | mcp_types.BlobResourceContents


class TruncatedBlock(BaseModel):
    """Represents a partially returned resource block with truncation metadata."""

    kind: Literal["truncated"] = "truncated"
    block_index: int = Field(description="Index of this block in the full resource (0-based)")
    started_at: int = Field(description="Byte offset where returned content starts within this block")
    ended_at: int = Field(description="Byte offset where returned content ends within this block")
    full_size: int = Field(description="Total size of the complete block in bytes")
    content: BaseResourceContents = Field(description="The partial content for this block")
    model_config = ConfigDict(extra="forbid")


BlockContent = Annotated[BaseResourceContents | TruncatedBlock, Field(discriminator="kind")]


class ReadBlocksArgs(OpenAIStrictModeBaseModel):
    server: str = Field(description="Origin MCP server name")
    uri: str = Field(description="Resource URI")
    start_block: int = Field(ge=0, description="Block index to start from (0-based)")
    start_offset: int = Field(ge=0, description="Byte offset within start_block to begin reading")
    max_bytes: int | None = Field(
        description=f"Maximum bytes to return (None means use default limit of {DEFAULT_MAX_BYTES:,} bytes)"
    )


class ReadBlocksResult(BaseModel):
    """Result of reading resource blocks."""

    blocks: list[mcp_types.TextResourceContents | mcp_types.BlobResourceContents | TruncatedBlock] = Field(
        description="Resource content blocks, with TruncatedBlock markers for partial blocks"
    )
    model_config = ConfigDict(extra="forbid")


def _normalize_parts(
    contents: Sequence[mcp_types.TextResourceContents | mcp_types.BlobResourceContents],
) -> list[NormalizedPart]:
    """Normalize resource parts to a small, typed internal shape."""
    norm: list[NormalizedPart] = []
    for p in contents:
        if isinstance(p, mcp_types.TextResourceContents):
            norm.append(TextPart(mime=p.mimeType, raw_bytes=p.text.encode("utf-8")))
            continue
        if isinstance(p, mcp_types.BlobResourceContents):
            base = p.blob  # base64 string per MCP spec
            norm.append(BlobPart(mime=p.mimeType, raw_str=str(base)))
            continue
        raise TypeError(f"Unsupported resource content type: {type(p).__name__}")
    return norm


def _iter_window_parts(
    contents: Sequence[mcp_types.TextResourceContents | mcp_types.BlobResourceContents],
    start_offset: int,
    max_bytes: int | None,
) -> Iterator[WindowedPart]:
    remaining: int | None = max_bytes if isinstance(max_bytes, int) and max_bytes > 0 else None
    cursor = 0
    for part in _normalize_parts(contents):
        mime = part.mime
        if isinstance(part, TextPart):
            raw: bytes = part.raw_bytes
            total_len = len(raw)
            if remaining is None or remaining > 0:
                start_in_part = max(0, start_offset - cursor)
                take_cap = remaining if isinstance(remaining, int) else total_len
                take = max(0, min(take_cap, total_len - start_in_part))
                if take > 0:
                    chunk = raw[start_in_part : start_in_part + take]
                    yield WindowedTextPart(
                        mime=mime,
                        text=chunk.decode("utf-8", errors="replace"),
                        total_bytes=total_len,
                        bytes_returned=take,
                    )
                    if remaining is not None:
                        remaining -= take
            cursor += total_len
        elif isinstance(part, BlobPart):
            base: str = part.raw_str
            total_len = len(base)
            if remaining is None or remaining > 0:
                start_in_part = max(0, start_offset - cursor)
                take_cap = remaining if isinstance(remaining, int) else total_len
                take = max(0, min(take_cap, total_len - start_in_part))
                if take > 0:
                    yield WindowedBlobPart(
                        mime=mime,
                        base64=base[start_in_part : start_in_part + take],
                        total_bytes=total_len,
                        bytes_returned=take,
                    )
                    if remaining is not None:
                        remaining -= take
            cursor += total_len
        if remaining is not None and remaining <= 0:
            break


def _build_window_payload(
    contents: Sequence[mcp_types.TextResourceContents | mcp_types.BlobResourceContents],
    start_offset: int,
    max_bytes: int | None,
) -> ResourceReadResult:
    # TODO: Optimization for full resource reads
    # When reading a full resource (start_offset=0 and max_bytes covers the entire resource),
    # return the content as native MCP blocks instead of the current windowed response format.
    # This would be more efficient and idiomatic for full resource reads.
    # Current behavior: Always returns windowed response with {"window": {...}, "parts": [...], "total_parts": N}
    # Proposed: When full resource is read, return as standard MCP TextResourceContents or BlobResourceContents
    parts_out: list[WindowedPart] = list(_iter_window_parts(contents, start_offset, max_bytes))
    return ResourceReadResult(
        window=ResourceWindowInfo(start_offset=start_offset, max_bytes=max_bytes or 0),
        parts=parts_out,
        total_parts=len(contents),
    )


def make_resources_server(name: str = "resources", *, compositor: Compositor) -> EnhancedFastMCP:
    """Create a MCP server that aggregates resources across servers.

    Args:
        name: Server name
        compositor: Compositor for resource operations, metadata, and lifecycle listeners

    - Synthetic server injected by the runtime; reserved name is ``resources``.
    - Provides a uniform API to discover and read resources exposed by other servers.
    - Only servers that advertise ``initialize.capabilities.resources`` are queried.

    **Policy enforcement architecture:**
    - LLM tool calls to this server go through the policy gateway (tool-level enforcement)
    - This server's internal operations use direct compositor methods to avoid client dependency
    - This prevents double policy enforcement and keeps the resources server as a pure facade

    **Window semantics:**
    - Windowing is byte-based across the concatenation of all parts reported by the
      underlying server. Text is sliced by UTF-8 bytes and decoded with
      ``errors="replace"`` if a multi-byte character is split at the boundary.
    - Base64 parts are sliced as base64 text; decoding is the caller's responsibility.
    """
    # TODO: Ensure NotificationsHandler is consistently injected when mounting this server,
    # or make subscription functionality optionally toggleable (don't advertise subscribe
    # tools if no handler is wired, to avoid promising notifications we can't deliver).
    mcp = EnhancedFastMCP(
        name,
        instructions=(
            "Resources aggregator for accessing MCP resources across all mounted servers.\n\n"
            "**Access model:** Resources are identified by (server, URI) pairs. Each resource belongs to "
            "a specific MCP server that exposes it. Use this server to discover what resources are available "
            "and read their contents without directly connecting to each origin server.\n\n"
            "**Discovery:** Use `list` to find available resources (optionally filtered by server name or URI prefix). "
            "Each result includes the origin server name and the resource URI. "
            "Use `list_resource_templates` to discover URI templates (RFC 6570) that describe patterns "
            "for constructing parameterized resource URIs.\n\n"
            "**Reading:** Use `read` to fetch resource contents by specifying the (server, URI) pair. "
            "Supports optional windowing for large resources (e.g., read lines 100-200 from a text resource).\n\n"
            "**Subscriptions:** Use `subscribe`/`unsubscribe` to track individual resource updates, "
            "or `subscribe_list_changes`/`unsubscribe_list_changes` to track when a server's resource list changes. "
            "Check the subscriptions index resource for current subscription state.\n\n"
            "**Important:** Resources are server-specific - the same URI path on different servers "
            "represents different resources. Always specify both server and URI when accessing resources.\n\n"
            "Note: Only servers that advertise the resources capability in their initialize response are queried."
        ),
    )

    # ---- Subscriptions index (single resource) -----------------------------
    # Internal store for subscriptions made via this server's subscribe tool.
    # No principals for now; keys are (server, uri).
    subs_lock = asyncio.Lock()
    subs: dict[tuple[str, str], SubscriptionRecord] = {}
    # Selected origins for list-changed subscriptions (multi-origin)
    list_subscribed_servers: set[str] = set()

    async def _broadcast_subs_updated() -> None:
        await mcp.broadcast_resource_updated(RESOURCES_SUBSCRIPTIONS_INDEX_URI)

    async def _present_servers() -> set[str]:
        # Include all mounted servers, including in-proc mounts without typed specs.
        # Use compositor._mount_names() directly; do not swallow errors.
        names = await compositor._mount_names()
        return set(names)

    def _get_or_create_sub(server: str, uri: str) -> SubscriptionRecord:
        key = (server, uri)
        rec = subs.get(key)
        if rec is None:
            rec = SubscriptionRecord(server=server, uri=uri)
            subs[key] = rec
        return rec

    async def _require_running_entry(server: str) -> RunningServerEntry:
        """Fetch the running server entry for a mounted server or raise a ToolError.

        This uses the Compositor's typed entries to ensure we have the
        InitializeResult for capabilities checks.
        """
        entries = await compositor.server_entries()
        entry = entries.get(server)
        if entry is None:
            raise ToolError(f"Unknown server '{server}'")
        if not isinstance(entry, RunningServerEntry):
            raise ToolError(f"Server '{server}' is not running (state={entry.state})")
        return entry

    async def _ensure_capability(server: str, *, feature: ResourceCapabilityFeature) -> None:
        """Ensure the target server advertises a required resources capability.

        Supported feature values:
        - ResourceCapabilityFeature.SUBSCRIBE: requires initialize.capabilities.resources.subscribe is True
        - ResourceCapabilityFeature.LIST_CHANGED: requires initialize.capabilities.resources.listChanged is True
        """
        entry = await _require_running_entry(server)
        try:
            caps = entry.initialize.capabilities
            res_caps = caps.resources
        except AttributeError as e:
            raise ToolError(f"Server '{server}' does not advertise resources capabilities") from e

        if res_caps is None:
            raise ToolError(f"Server '{server}' does not advertise resources capabilities")

        if feature is ResourceCapabilityFeature.SUBSCRIBE:
            ok = bool(res_caps.subscribe)
            needed = "resources.subscribe"
        elif feature is ResourceCapabilityFeature.LIST_CHANGED:
            ok = bool(res_caps.listChanged)
            needed = "resources.listChanged"
        else:
            raise ToolError(f"Unknown capability feature: {feature}")

        if not ok:
            raise ToolError(f"Server '{server}' does not support {needed}")

    @mcp.resource(
        RESOURCES_SUBSCRIPTIONS_INDEX_URI,
        name="resources.subscriptions",
        mime_type="application/json",
        description=("Index of resource subscriptions made via the resources server."),
    )
    async def subscriptions_index() -> SubscriptionsIndex:
        present = await _present_servers()
        async with subs_lock:
            items = list(subs.values())
            lss = set(list_subscribed_servers)
        out = [
            SubscriptionSummary(
                server=rec.server,
                uri=rec.uri,
                pinned=rec.pinned,
                present=(rec.server in present),
                active=rec.active and (rec.server in present),
                last_error=rec.last_error,
            )
            for rec in items
        ]
        list_out: list[ListSubscriptionSummary] = [
            ListSubscriptionSummary(server=s, present=(s in present), active=(s in present)) for s in sorted(lss)
        ]
        return SubscriptionsIndex(subscriptions=out, list_subscriptions=list_out)

    # TODO: Investigate if agents can subscribe to resource template list changes.
    # The MCP protocol does not currently define template list change notifications
    # (only resource list changes via notifications/resources/list_changed).
    # If/when MCP adds template notifications, add subscribe_template_list_changes
    # and unsubscribe_template_list_changes tools following the same pattern as
    # subscribe_list_changes/unsubscribe_list_changes.

    @mcp.flat_model()
    async def list_resources_tool(input: ResourcesListArgs) -> ResourcesListResult:
        """List MCP resources that are exposed by servers (if any). Filter by server name or URI prefix if desired.

        Returns only resources that MCP servers explicitly expose via the resources capability.
        Call this first to see what resources are available before trying to read them.
        """
        # Call compositor's internal _list_resources_mcp directly to avoid client dependency
        # (resources server is tightly coupled to compositor for subscriptions/notifications/metadata)
        mcp_list = await compositor._list_resources_mcp()
        specs = await compositor.mount_specs()
        mount_names = list(specs.keys())
        out: list[ResourceEntry] = []
        for r in mcp_list:
            uri_str = str(r.uri)
            try:
                origin = derive_origin_server(uri_str, mount_names, compositor.resource_prefix_format)
            except ValueError:
                # Skip resources that don't match any known server
                continue
            if input.server and origin != input.server:
                continue
            # If a uri_prefix filter is provided, match against the raw (de-prefixed) URI
            if input.uri_prefix:
                raw_uri = remove_resource_prefix(uri_str, origin, compositor.resource_prefix_format)
                if not raw_uri.startswith(input.uri_prefix):
                    continue
            out.append(ResourceEntry(server=origin, resource=r))
        return ResourcesListResult(resources=out)

    @mcp.flat_model()
    async def list_resource_templates() -> ResourceTemplatesListResult:
        """List URI templates (RFC 6570) that servers expose for constructing resource URIs, tagged by origin server.

        Returns templates only from servers that expose them via the resources capability.
        Use this to discover what resource URIs can be constructed (e.g., resource://runtime/container.info).
        """
        # Query each mounted server individually to track template ownership
        entries = await compositor.server_entries()
        out: list[ResourceTemplateEntry] = []
        for server_name, entry in entries.items():
            if not isinstance(entry, RunningServerEntry):
                continue
            # Only query servers that advertise resources capability
            # (templates are part of the resources capability)
            if entry.initialize.capabilities.resources is None:
                continue
            # Query this server's templates
            child_client = compositor.get_child_client(server_name)
            templates = await child_client.list_resource_templates()
            for template in templates:
                out.append(ResourceTemplateEntry(server=server_name, template=template))
        return ResourceTemplatesListResult(templates=out)

    @mcp.flat_model()
    async def read(input: ResourcesReadArgs) -> ResourceReadResult:
        """Read contents of an MCP resource that a server exposes. Use start_offset and max_bytes for pagination.

        Only works for resources that servers explicitly expose via their resources capability.
        Use list_resources_tool first to see what resources are available.
        """
        prefixed = add_resource_prefix(input.uri, input.server, compositor.resource_prefix_format)
        uri_value = ANY_URL.validate_python(prefixed)
        # Call compositor method that converts FastMCP types to MCP protocol types
        # (resources server is tightly coupled to compositor for subscriptions/notifications/metadata)
        contents = await compositor.read_resource_contents(uri_value)
        max_bytes = input.max_bytes if input.max_bytes is not None else DEFAULT_MAX_BYTES
        return _build_window_payload(contents, input.start_offset, max_bytes)

    @mcp.flat_model()
    async def read_blocks(input: ReadBlocksArgs) -> ReadBlocksResult:
        """Read MCP resource with block-level windowing. Returns complete blocks plus truncation markers for partial blocks.

        Only works for resources that servers explicitly expose via their resources capability.
        Use list_resources_tool first to see what resources are available.

        Size semantics:
        - Text blocks: size measured in UTF-8 bytes (not characters)
        - Blob blocks: size measured in base64 string length (not decoded bytes)
        - max_bytes limit applies to the sum across all block types

        Slicing behavior:
        - Text: slice at UTF-8 byte boundaries (may split multi-byte characters, uses errors='replace')
        - Blob: slice base64 string directly (always valid since base64 is ASCII)
        """
        prefixed = add_resource_prefix(input.uri, input.server, compositor.resource_prefix_format)
        uri_value = ANY_URL.validate_python(prefixed)
        contents = await compositor.read_resource_contents(uri_value)

        max_bytes = input.max_bytes if input.max_bytes is not None else DEFAULT_MAX_BYTES
        result_blocks: list[mcp_types.TextResourceContents | mcp_types.BlobResourceContents | TruncatedBlock] = []
        bytes_accumulated = 0

        for block_idx, block in enumerate(contents):
            # Skip blocks before start_block
            if block_idx < input.start_block:
                continue

            # Get block size
            if isinstance(block, mcp_types.TextResourceContents):
                # For text, measure size in UTF-8 bytes
                block_bytes = block.text.encode("utf-8")
                block_size = len(block_bytes)
                is_text = True
            elif isinstance(block, mcp_types.BlobResourceContents):
                # For blob, size is base64 string length (no need for bytes representation)
                block_size = len(block.blob)
                is_text = False
                block_bytes = b""  # Not used for blobs
            else:
                raise TypeError(f"Unsupported content type: {type(block).__name__}")

            # Determine slice range for this block
            slice_start = input.start_offset if block_idx == input.start_block else 0
            remaining_budget = max_bytes - bytes_accumulated

            if slice_start >= block_size:
                # start_offset is beyond this block, skip it
                continue

            available_in_block = block_size - slice_start
            can_take = min(available_in_block, remaining_budget)

            sliced_content: BaseResourceContents
            if can_take >= available_in_block:
                # Can include full remainder of block
                if slice_start == 0:
                    # Full block, no truncation
                    result_blocks.append(block)
                else:
                    # Partial from start
                    slice_end = block_size
                    if is_text:
                        sliced_bytes = block_bytes[slice_start:slice_end]
                        sliced_content = mcp_types.TextResourceContents(
                            uri=block.uri, mimeType=block.mimeType, text=sliced_bytes.decode("utf-8", errors="replace")
                        )
                    else:
                        # blob is base64 string, slice directly
                        assert isinstance(block, mcp_types.BlobResourceContents)
                        sliced_content = mcp_types.BlobResourceContents(
                            uri=block.uri, mimeType=block.mimeType, blob=block.blob[slice_start:slice_end]
                        )
                    result_blocks.append(
                        TruncatedBlock(
                            block_index=block_idx,
                            started_at=slice_start,
                            ended_at=slice_end,
                            full_size=block_size,
                            content=sliced_content,
                        )
                    )
                bytes_accumulated += available_in_block
            else:
                # Must truncate this block
                slice_end = slice_start + can_take
                if is_text:
                    sliced_bytes = block_bytes[slice_start:slice_end]
                    sliced_content = mcp_types.TextResourceContents(
                        uri=block.uri, mimeType=block.mimeType, text=sliced_bytes.decode("utf-8", errors="replace")
                    )
                else:
                    # blob is base64 string, slice directly
                    assert isinstance(block, mcp_types.BlobResourceContents)
                    sliced_content = mcp_types.BlobResourceContents(
                        uri=block.uri, mimeType=block.mimeType, blob=block.blob[slice_start:slice_end]
                    )
                result_blocks.append(
                    TruncatedBlock(
                        block_index=block_idx,
                        started_at=slice_start,
                        ended_at=slice_end,
                        full_size=block_size,
                        content=sliced_content,
                    )
                )
                bytes_accumulated += can_take
                break  # Hit budget limit

            if bytes_accumulated >= max_bytes:
                break

        return ReadBlocksResult(blocks=result_blocks)

    @mcp.flat_model()
    async def subscribe(input: ResourcesSubscribeArgs) -> SimpleOk:
        """Subscribe to updates for a resource."""
        await _ensure_capability(input.server, feature=ResourceCapabilityFeature.SUBSCRIBE)
        prefixed = add_resource_prefix(input.uri, input.server, compositor.resource_prefix_format)
        uri_value = ANY_URL.validate_python(prefixed)
        # Attempt subscribe; reflect success/error in index and re-raise on error.
        try:
            # Use the child's persistent session directly (already connected)
            child_client = compositor.get_child_client(input.server)
            await child_client.session.subscribe_resource(uri_value)
        except McpError as e:
            async with subs_lock:
                rec = _get_or_create_sub(input.server, input.uri)
                rec.active = False
                rec.last_error = f"{type(e).__name__}: {e}"
            await _broadcast_subs_updated()
            # Do not degrade on missing method; capability check should prevent reaching here
            raise
        else:
            async with subs_lock:
                rec = _get_or_create_sub(input.server, input.uri)
                rec.active = True
                rec.last_error = None
            await _broadcast_subs_updated()
            return SimpleOk(ok=True)

    @mcp.flat_model()
    async def unsubscribe(input: ResourcesSubscribeArgs) -> SimpleOk:
        """Unsubscribe from updates for a resource."""
        await _ensure_capability(input.server, feature=ResourceCapabilityFeature.SUBSCRIBE)
        prefixed = add_resource_prefix(input.uri, input.server, compositor.resource_prefix_format)
        uri_value = ANY_URL.validate_python(prefixed)
        rec_key = (input.server, input.uri)
        try:
            child_client = compositor.get_child_client(input.server)
            await child_client.session.unsubscribe_resource(uri_value)
        except McpError as e:
            # Reflect error in index and re-raise
            async with subs_lock:
                if (rec := subs.get(rec_key)) is not None:
                    rec.active = False
                    rec.last_error = f"{type(e).__name__}: {e}"
            await _broadcast_subs_updated()
            # Do not degrade on missing method; capability check should prevent reaching here
            raise
        else:
            # Remove record entirely on explicit unsubscribe (no pin semantics yet)
            async with subs_lock:
                subs.pop(rec_key, None)
            await _broadcast_subs_updated()
            return SimpleOk(ok=True)

    @mcp.flat_model(name="subscribe_list_changes")
    async def subscribe_list_changes(input: ListSubscribeArgs) -> SimpleOk:
        """Track when a server's resource list changes. Can subscribe to multiple servers."""
        await _ensure_capability(input.server, feature=ResourceCapabilityFeature.LIST_CHANGED)
        async with subs_lock:
            list_subscribed_servers.add(input.server)
        await _broadcast_subs_updated()
        return SimpleOk(ok=True)

    @mcp.flat_model(name="unsubscribe_list_changes")
    async def unsubscribe_list_changes(input: ListSubscribeArgs) -> SimpleOk:
        """Stop tracking resource list changes for a server."""
        async with subs_lock:
            list_subscribed_servers.discard(input.server)
        await _broadcast_subs_updated()
        return SimpleOk(ok=True)

    # Respond to Compositor lifecycle to keep index correct: tear down underlying
    # subscriptions on unmount, do not auto-rehydrate on mount. Non-pinned subs are
    # dropped; pinned kept inactive (no pin controls yet — placeholder for future).
    async def _on_mount_change(name: str, action: MountEvent) -> None:
        if action is not MountEvent.UNMOUNTED:
            return
        # Server is being unmounted. Do not attempt remote unsubscriptions; the
        # Compositor tears down underlying sessions. Update local records only.
        # Drop non-pinned entries for this server; mark pinned (future) inactive.
        async with subs_lock:
            to_delete = [(server, uri) for (server, uri), rec in subs.items() if server == name and not rec.pinned]
            for (server, uri), rec in list(subs.items()):
                if server == name and rec.pinned:
                    rec.active = False
                    subs[(server, uri)] = rec
            changed = bool(to_delete)
            for key in to_delete:
                subs.pop(key, None)
            # Drop list-changed selection for this origin if it is unmounted
            if name in list_subscribed_servers:
                list_subscribed_servers.discard(name)
                changed = True
        if changed:
            await _broadcast_subs_updated()

    compositor.add_mount_listener(_on_mount_change)

    # React to compositor list-changed notifications and reflect updates to the index
    async def _on_list_changed(name: str) -> None:
        async with subs_lock:
            subscribed = set(list_subscribed_servers)
        if name in subscribed:
            await _broadcast_subs_updated()

    compositor.add_resource_list_change_listener(_on_list_changed)

    # React to compositor resource-updated notifications: if a subscribed
    # resource (server, uri) matches, broadcast index update so UIs refresh.
    async def _on_resource_updated(name: str, uri: str) -> None:
        key = (name, uri)
        async with subs_lock:
            rec = subs.get(key)
            is_active = bool(rec and rec.active)
        if is_active:
            await _broadcast_subs_updated()

    compositor.add_resource_updated_listener(_on_resource_updated)

    # TODO: Consider per-subscription resources like
    #   resources://subscriptions/{server}/{percent-encoded-uri}
    # to enable list_changed semantics. For now, a single index resource is enough.

    return mcp
