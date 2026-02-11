from __future__ import annotations

from collections.abc import Iterable
from mcp import types as mcp_types
from pydantic import BaseModel, Field


class ResourcesServerNotice(BaseModel):
    """Per-server resources notice.

    - updated: immutable set of resource URIs updated for this server
    - list_changed: whether resources/list changed for this server
    """

    updated: frozenset[str] = Field(
        default_factory=frozenset,
        description="Resource URIs that were updated"
    )
    list_changed: bool = Field(
        default=False,
        description="Whether resources/list changed"
    )


class NotificationsBatch(BaseModel):
    """Buffered notifications grouped by server for efficient consumption."""

    resources: dict[str, ResourcesServerNotice] = Field(
        default_factory=dict,
        description="Per-server resources notice: {server -> {updated, list_changed}}"
    )

    def iter_updated_uris(self) -> Iterable[tuple[str, str]]:
        """Iterate over (server, uri) pairs for all updated resources."""
        for server, notice in self.resources.items():
            for uri in notice.updated:
                yield (server, uri)

    def get_servers_with_list_changes(self) -> set[str]:
        """Get set of server names where resources/list changed."""
        return {
            server
            for server, notice in self.resources.items()
            if notice.list_changed
        }
