from __future__ import annotations

from mcp import types as mcp_types
from pydantic import BaseModel, Field


class ResourceUpdateEvent(BaseModel):
    """Derived resource update event for agent/UI consumption (no synthetic counters)."""

    server: str = Field(description="Origin MCP server name (derived)")
    uri: str = Field(description="Resource URI string for the update")


class NotificationsBatch(BaseModel):
    """Buffered notifications ready to be injected as model input or observed by UI.

    Fields
    - resources_updated: derived per-update events with server+URI
    - resource_list_changed: list of server names where resources/list changed
    - raw: full MCP notification payloads captured for display/debugging
    """

    resources_updated: list[ResourceUpdateEvent] = Field(
        default_factory=list, description="Derived resource update events (server, uri, version)"
    )
    resource_list_changed: list[str] = Field(default_factory=list, description="Servers with resources/list changed")
    # Raw MCP server notifications captured (only resources notifications are buffered here)
    raw: list[mcp_types.ResourceUpdatedNotification | mcp_types.ResourceListChangedNotification] = Field(
        default_factory=list, description="Full MCP resources notifications captured for display/debugging"
    )


class ResourcesServerNotice(BaseModel):
    """Per-server resources notice.

    - updated: list of resource URIs updated for this server
    - list_changed: whether a resources/list_changed occurred for this server (best effort)
    """

    updated: list[str] = Field(default_factory=list)
    list_changed: bool = False


class NotificationsForModel(BaseModel):
    """Top-level structured notification envelope used for message injection."""

    resources: dict[str, ResourcesServerNotice] = Field(
        default_factory=dict, description="Per-server resources notice: {server -> {updated, list_changed}}"
    )
