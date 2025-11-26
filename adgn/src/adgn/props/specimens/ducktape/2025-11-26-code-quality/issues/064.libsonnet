local I = import '../../specimens/lib.libsonnet';

// iss-064: Delete unused _StubGatewayClient and _StubGatewaySession classes

I.issueOneOccurrence(
  rationale=|||
    Tests define `_StubGatewayClient` and `_StubGatewaySession` stub classes but never
    actually use them. They're created as `gw = _StubGatewayClient()` but the `gw`
    variable is never referenced.

    **Current pattern:**
    ```python
    class _StubGatewaySession:
        async def subscribe_resource(self, uri: str) -> None:
            return None

        async def unsubscribe_resource(self, uri: str) -> None:
            return None


    class _StubGatewayClient:
        def __init__(self) -> None:
            self.session = _StubGatewaySession()


    async def test_something():
        # ...
        gw = _StubGatewayClient()  # Created but never used!
        res_server = make_resources_server(name="resources", compositor=comp)
        # gw is not passed to make_resources_server or used anywhere
        # ...
    ```

    **Problems:**
    1. Dead code - classes are defined but never used
    2. Confusing - suggests gateway client is needed but it's not
    3. Misleading names - `_StubGatewayClient` suggests it's for gateway, but it's actually
       intended for compositor (based on the session methods)
    4. Adds noise to test files

    **Fix:** Delete both classes and the `gw = _StubGatewayClient()` instantiations.

    **Investigation:** Check if these were intended to be passed to `make_resources_server()`
    but aren't actually needed. The resources server seems to work without any gateway client
    in these tests.
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
