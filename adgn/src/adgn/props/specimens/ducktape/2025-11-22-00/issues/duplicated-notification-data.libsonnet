local I = import '../../specimens/lib.libsonnet';

// iss-026: Duplicated notification data and redundant data structures

I.issueOneOccurrence(
  rationale= |||
    The notifications module duplicates data in two ways:

    **Problem 1: NotificationsBatch stores parsed and raw data**

    `NotificationsBatch` (types.py:14-30) has three fields: `resources_updated` (parsed),
    `resource_list_changed` (parsed), and `raw` (original MCP notifications). Parsed
    fields are derivable from `raw`, creating redundant storage, sync risk, and unclear
    source of truth.

    **Problem 2: Two redundant representations**

    Both `NotificationsBatch` and `NotificationsForModel` (types.py:33-51) represent the
    same notification data in different shapes:
    - `NotificationsBatch`: flat lists
    - `NotificationsForModel`: grouped by server

    **Solution: Single grouped representation**

    | Aspect | Current | Correct |
    |--------|---------|---------|
    | Storage | 3 fields (parsed + raw) | 1 grouped dict |
    | Types | 2 classes | 1 class |
    | Deduplication | Manual | frozenset[str] |
    | Parsing | On access | Via `from_raw()` classmethod |

    Keep only the efficient grouped shape:

    ```python
    class NotificationsBatch(BaseModel):
        resources: dict[str, ResourcesServerNotice]  # {server: {updated, list_changed}}

        @classmethod
        def from_raw(cls, notifications) -> NotificationsBatch:
            # Parse once at construction, derive grouped structure
    ```

    **Benefits:**
    - Single source of truth (derived from raw on construction)
    - No duplication (parsed data not stored alongside raw)
    - Efficient lookups (grouped by server, frozenset deduplication)
    - Helper methods for access patterns (iter_updated_uris, get_servers_with_list_changes)

    **Migration:** Remove `NotificationsForModel`, replace `NotificationsBatch` with merged
    shape, update callers to use grouped structure.

    **Principle:** Store data in ONE efficient representation, derive views on-demand.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/notifications/types.py': [
      [14, 30],  // NotificationsBatch with redundant fields
      [33, 49],  // ResourcesServerNotice and NotificationsForModel (redundant with NotificationsBatch)
    ],
  },
)
