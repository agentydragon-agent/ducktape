local I = import '../../lib.libsonnet';

// Merged: test-unused-stub-gateway-classes, test-unused-gw-context-manager,
// setup-unused-gateway-param
// All describe unused gateway-related infrastructure that should be deleted

I.issue(
  expect_caught_from=[
    ['adgn/tests/mcp/resources/test_list_changes_subscriptions.py'],
    ['adgn/tests/mcp/resources/test_subscriptions_index.py'],
    ['adgn/tests/mcp/test_resources_subscriptions_index.py'],
    ['adgn/tests/mcp/resources/test_notifications.py'],
    ['adgn/src/adgn/mcp/compositor/setup.py'],
  ],
  rationale= |||
    Unused gateway-related infrastructure (stub classes, variables, parameters) that
    should be deleted. Dead code adds maintenance burden without providing value.

    **Three categories of unused gateway infrastructure:**

    **1. Test stub classes and variables (never used after definition)**

    Multiple test files define `_StubGatewaySession` and `_StubGatewayClient` stub classes
    with subscribe/unsubscribe methods, then instantiate as `gw = _StubGatewayClient()`,
    but the gw variable is never used afterward. Not passed to make_resources_server() or
    referenced in test logic.

    Locations:
    - test_list_changes_subscriptions.py: stub classes (lines 12-22), unused gw (lines 30, 53)
    - test_subscriptions_index.py: stub classes (lines 14-24), unused gw (line 51)
    - test_resources_subscriptions_index.py: stub classes (lines 14-24)

    **2. Unused async context manager and server variable (test_notifications.py)**

    Lines 29-31 create `gw_server = FastMCP("gw")` and `async with Client(gw_server) as gw:`
    context manager, but the gw variable is never used. Comment says "placeholder gateway
    client" but it's creating a compositor client that isn't needed.

    **3. Unused function parameter (setup.py:21)**

    The `gateway_client` parameter is checked with `if gateway_client is not None` but its
    value is never referenced in the function body. This is dead conditional logic.

    **Problems with unused infrastructure:**
    - Maintenance burden (must update when interfaces change)
    - Confuses readers (looks important but serves no purpose)
    - Suggests missing functionality (why define if not used?)
    - Makes tests harder to understand (extra noise)

    **Correct approach: Delete unused code**

    - Delete stub class definitions and unused variable instantiations from tests
    - Delete the unused context manager block and gw_server variable
    - Replace unused gateway_client parameter with explicit mount_resources: bool = True
      parameter to control whether resources server is mounted (update docstring)

    Tests should only create infrastructure they actually use. Parameters should only
    exist if their values are referenced.
  |||,
  filesToRanges={
    'adgn/tests/mcp/resources/test_list_changes_subscriptions.py': [
      [12, 22],  // _StubGatewaySession and _StubGatewayClient definitions
      [30, 30],  // gw = _StubGatewayClient() - never used
      [53, 53],  // gw = _StubGatewayClient() - never used
    ],
    'adgn/tests/mcp/resources/test_subscriptions_index.py': [
      [14, 24],  // Stub class definitions
      [51, 51],  // gw = _StubGatewayClient() - never used
    ],
    'adgn/tests/mcp/test_resources_subscriptions_index.py': [
      [14, 24],  // Stub class definitions
    ],
    'adgn/tests/mcp/resources/test_notifications.py': [
      [29, 31],  // Unused gw_server and context manager
    ],
    'adgn/src/adgn/mcp/compositor/setup.py': [
      [21, 21],  // gateway_client parameter checked but never used
    ],
  },
)
