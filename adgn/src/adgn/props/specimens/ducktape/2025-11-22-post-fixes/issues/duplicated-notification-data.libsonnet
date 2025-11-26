local I = import '../../specimens/lib.libsonnet';

// iss-026: Duplicated notification data and redundant data structures

I.issueOneOccurrence(
  rationale= |||
    The notifications module has two related problems:

    **Problem 1: NotificationsBatch duplicates parsed and raw data**

    `NotificationsBatch` stores the same information three times: in `resources_updated`
    (parsed), `resource_list_changed` (parsed), and `raw` (original MCP notifications).
    The parsed fields are completely derivable from `raw`, making them redundant storage.

    **Current implementation (types.py, lines 14-30):**
    ```python
    class NotificationsBatch(BaseModel):
        """Buffered notifications ready to be injected as model input or observed by UI."""

        resources_updated: list[ResourceUpdateEvent] = Field(
            default_factory=list, description="Derived resource update events (server, uri, version)"
        )
        resource_list_changed: list[str] = Field(
            default_factory=list, description="Servers with resources/list changed"
        )
        # Raw MCP server notifications captured (only resources notifications are buffered here)
        raw: list[mcp_types.ResourceUpdatedNotification | mcp_types.ResourceListChangedNotification] = Field(
            default_factory=list, description="Full MCP resources notifications captured for display/debugging"
        )
    ```

    **Problems with duplication:**

    1. **Redundant storage**: Same data in three fields (2 parsed + 1 raw)
    2. **Sync risk**: Parsed fields could become out-of-sync with raw
    3. **Memory overhead**: Storing everything twice
    4. **Unclear source of truth**: Is `raw` or parsed fields authoritative?
    5. **Maintenance burden**: Must keep all three fields consistent

    **Problem 2: NotificationsBatch and NotificationsForModel are redundant**

    Both classes represent the same notification data, just in different shapes:
    - `NotificationsBatch`: flat lists (`resources_updated: list[ResourceUpdateEvent]`)
    - `NotificationsForModel`: grouped by server (`resources: dict[str, ResourcesServerNotice]`)

    **Current implementation (types.py, lines 33-51):**
    ```python
    class ResourcesServerNotice(BaseModel):
        """Per-server resources notice."""
        updated: list[str] = Field(default_factory=list)
        list_changed: bool = False


    class NotificationsForModel(BaseModel):
        """Top-level structured notification envelope used for message injection."""
        resources: dict[str, ResourcesServerNotice] = Field(
            default_factory=dict, description="Per-server resources notice: {server -> {updated, list_changed}}"
        )
    ```

    **Problems with two representations:**

    1. **Redundant types**: Two classes for the same data
    2. **Conversion overhead**: Must convert between shapes
    3. **Unclear which to use**: When should code use which representation?
    4. **More efficient shape exists**: `NotificationsForModel` groups by server (better for lookups)
    5. **Duplication of concerns**: Both track resource updates and list changes

    **The correct approach:**

    Keep only the efficient, grouped representation (`NotificationsForModel` shape):

    ```python
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

        # Optional: keep raw only for debugging/logging, not for runtime use
        # raw: list[mcp_types.ResourceUpdatedNotification | ...] = Field(exclude=True)

        @classmethod
        def from_raw(
            cls,
            notifications: list[mcp_types.ResourceUpdatedNotification | mcp_types.ResourceListChangedNotification]
        ) -> NotificationsBatch:
            """Parse raw MCP notifications into grouped batch."""
            resources: dict[str, ResourcesServerNotice] = {}

            for notif in notifications:
                # Extract server name from notification
                server = extract_server_from_notification(notif)

                if server not in resources:
                    resources[server] = ResourcesServerNotice()

                if isinstance(notif, mcp_types.ResourceUpdatedNotification):
                    # Add URI to updated set
                    resources[server].updated |= {notif.params.uri}
                elif isinstance(notif, mcp_types.ResourceListChangedNotification):
                    resources[server].list_changed = True

            return cls(resources=resources)

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
    ```

    **Benefits:**

    1. **Single source of truth**: One representation, derived from raw on construction
    2. **No duplication**: Parsed data isn't stored alongside raw
    3. **Efficient lookups**: Grouped by server, deduplicated URIs (frozenset)
    4. **Clear API**: Methods to access data in different views
    5. **Type safety**: frozenset prevents accidental modification
    6. **Simpler codebase**: One type instead of two redundant ones

    **Why frozenset for URIs:**

    - Same URI can be updated multiple times (should only appear once)
    - Immutable (notifications shouldn't be modified after creation)
    - Fast membership testing
    - Clear intent: set of unique URIs

    **Migration path:**

    1. Replace `NotificationsBatch` with the merged shape
    2. Remove `NotificationsForModel` (use `NotificationsBatch` everywhere)
    3. Update callers to use the new shape (grouped by server)
    4. Add helper methods for common access patterns (iter_updated_uris, etc.)

    **When raw MCP notifications are needed:**

    - Logging/debugging: Log them immediately, don't store
    - Display: Convert to JSON on-demand, don't keep in memory
    - Testing: Construct `NotificationsBatch` directly with test data

    The principle: store data in ONE efficient representation, derive other views
    on-demand via methods/properties.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/notifications/types.py': [
      [14, 30],  // NotificationsBatch with redundant fields
      [33, 51],  // ResourcesServerNotice and NotificationsForModel (redundant with NotificationsBatch)
    ],
  },
)
