local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Three test files duplicate SQLite persistence setup instead of using a shared
    fixture, causing verbose destructuring patterns and inconsistency.

    **Duplication locations:**
    - test_policy_validation_reload.py (lines 18-36): Returns tuple requiring
      destructuring in 7 tests (lines 41, 54, 68, 84, 105, 120, 131)
    - test_separated_servers.py (lines 31-38): Creates persistence in fixture
    - test_ui_auth.py (lines 20-27): Identical pattern to test_separated_servers

    **Existing good pattern:** persist/conftest.py (lines 19-29) has clean
    persistence fixture using `SQLitePersistence(tmp_path / "test.db")` +
    `ensure_schema()`. Should be promoted to tests/agent/conftest.py for reuse.

    **Fixes:**
    1. Create shared persistence fixture in tests/agent/conftest.py
    2. Split test_policy_validation_reload.py fixtures to avoid tuple destructuring
    3. Update mcp_bridge tests to use shared fixture

    **Benefits:** Eliminates duplication, removes verbose destructuring, consistent
    pattern across agent tests.
  |||,
  filesToRanges={
    'adgn/tests/agent/test_policy_validation_reload.py': [
      [18, 36],  // engine_and_persistence fixture returning tuple
      [41, 41],  // engine, _ = destructuring
      [54, 54],  // engine, _ = destructuring
      [68, 68],  // engine, _ = destructuring
      [84, 84],  // engine, persistence = destructuring
      [105, 105], // engine, _ = destructuring
      [120, 120], // engine, _ = destructuring
      [131, 131], // engine, persistence = destructuring
    ],
    'adgn/tests/agent/mcp_bridge/test_separated_servers.py': [
      [31, 38],  // Duplicate persistence creation in infrastructure_registry
    ],
    'adgn/tests/agent/mcp_bridge/test_ui_auth.py': [
      [20, 27],  // Duplicate persistence creation in infrastructure_registry
    ],
  },
  expect_caught_from=[
    ['adgn/tests/agent/test_policy_validation_reload.py'],
    ['adgn/tests/agent/mcp_bridge/test_separated_servers.py'],
    ['adgn/tests/agent/mcp_bridge/test_ui_auth.py'],
  ],
)
