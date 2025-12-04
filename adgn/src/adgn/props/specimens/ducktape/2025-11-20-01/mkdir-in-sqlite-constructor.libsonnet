local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines cli.py:114-115 and app.py:152-153 manually call db_path.parent.mkdir() before
    instantiating SQLitePersistence. This duplicated directory setup should be handled
    internally by SQLitePersistence.__init__.

    Problems: violates DRY (every caller must remember mkdir), error-prone (forgetting
    mkdir yields cryptic SQLite errors), leaks implementation detail (callers shouldn't
    need to know SQLite requires parent directories), multiple call sites risk inconsistency.

    Move mkdir(parents=True, exist_ok=True) into SQLitePersistence.__init__ (lines 44-50).
    This is safe - mkdir is idempotent, and constructors are the right place for ensuring
    prerequisites. Benefits: simpler caller code, single responsibility, consistent behavior
    across all instances.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/cli.py': [
      [114, 115],  // Manual mkdir before SQLitePersistence
    ],
    'adgn/src/adgn/agent/server/app.py': [
      [152, 153],  // Manual mkdir before SQLitePersistence
    ],
    'adgn/src/adgn/agent/persist/sqlite.py': [
      [44, 50],  // SQLitePersistence.__init__ - should handle mkdir internally
    ],
  },
  expect_caught_from=[
    ['adgn/src/adgn/agent/mcp_bridge/cli.py'],
    ['adgn/src/adgn/agent/server/app.py'],
  ],
)
