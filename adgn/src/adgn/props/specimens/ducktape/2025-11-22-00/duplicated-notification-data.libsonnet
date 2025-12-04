local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    notifications/types.py duplicates data in two ways: (1) NotificationsBatch
    (lines 14-30) stores both parsed fields (resources_updated, resource_list_changed)
    and raw MCP notifications, creating redundancy and unclear source of truth;
    (2) NotificationsBatch and NotificationsForModel (lines 33-51) represent the same
    data in different shapes (flat lists vs grouped by server).

    Problems: Parsed fields are derivable from raw, creating sync risk. Two classes
    for the same data. Manual deduplication. No single source of truth.

    Replace with single grouped representation: one class with dict[server, notices],
    parse once at construction via from_raw() classmethod, use frozenset for
    deduplication. Remove NotificationsForModel entirely.

    Benefits: Single source of truth (derived from raw on construction), no
    duplication, efficient lookups (grouped by server), helper methods for access
    patterns.

    Principle: Store data in ONE efficient representation, derive views on-demand.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/notifications/types.py': [
      [14, 30],  // NotificationsBatch with redundant fields
      [33, 49],  // ResourcesServerNotice and NotificationsForModel (redundant with NotificationsBatch)
    ],
  },
)
