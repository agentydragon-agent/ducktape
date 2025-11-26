local I = import '../../specimens/lib.libsonnet';

// iss-064: Delete unused _StubGatewayClient and _StubGatewaySession classes

I.issueOneOccurrence(
  rationale=|||
    Tests define `_StubGatewayClient` and `_StubGatewaySession` stub classes but never
    actually use them. They're created as `gw = _StubGatewayClient()` but the `gw`
    variable is never referenced.

    **Current pattern:**
    Tests define `_StubGatewaySession` (with `subscribe_resource`/`unsubscribe_resource` methods)
    and `_StubGatewayClient` (holds a session), then instantiate `gw = _StubGatewayClient()` but
    never reference `gw` afterward. The variable is not passed to `make_resources_server()` or
    used anywhere in the test.

    **Problems:**
    1. Dead code - classes are defined but never used
    2. Confusing - suggests gateway client is needed but it's not
    3. Misleading names - `_StubGatewayClient` suggests it's for gateway, but it's actually
       intended for compositor (based on the session methods)
    4. Adds noise to test files

    **Verified:** The `gw` variable is created but never referenced after instantiation.
    `make_resources_server(name="resources", compositor=comp)` doesn't accept a gateway_client
    parameter. The resources server works without it. These stubs are dead code.

    **Fix:** Delete both classes and all `gw = _StubGatewayClient()` instantiations.
  |||,
  filesToRanges={
    'adgn/tests/mcp/resources/test_list_changes_subscriptions.py': [
      [12, 22],  // _StubGatewaySession and _StubGatewayClient class definitions
      [30, 30],  // gw = _StubGatewayClient() - never used
      [53, 53],  // gw = _StubGatewayClient() - never used (second test)
    ],
    'adgn/tests/mcp/resources/test_subscriptions_index.py': [
      [14, 24],  // _StubGatewaySession and _StubGatewayClient class definitions
      [51, 51],  // gw = _StubGatewayClient() - never used
    ],
    'adgn/tests/mcp/test_resources_subscriptions_index.py': [
      [14, 24],  // _StubGatewaySession and _StubGatewayClient class definitions
      // Note: Used in test_subscriptions_index_updates_on_unmount around line 51
    ],
  },
)
