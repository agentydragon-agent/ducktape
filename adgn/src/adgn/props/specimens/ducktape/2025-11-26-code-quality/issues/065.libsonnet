local I = import '../../specimens/lib.libsonnet';

// iss-065: Delete unused gw/gw_server variables that create compositor clients

I.issueOneOccurrence(
  rationale=|||
    Tests create variables named `gw` or `gw_server` that appear to be "gateway" related,
    but they're actually creating compositor clients. Worse, these variables are never
    actually used - they're just noise.

    **Pattern 1: Unused async context manager:**
    ```python
    async def test_resources_list_changed_notification():
        # Use a minimal FastMCP as a placeholder gateway client
        gw_server = FastMCP("gw")
        async with Client(gw_server) as gw:  # gw is never used!
            from adgn.mcp.compositor.server import Compositor
            comp = Compositor("comp")
            server = make_resources_server(name="resources", compositor=comp)
            # ... test logic that doesn't use gw at all ...
    ```

    **Pattern 2: Unused variable:**
    ```python
    async def test_something():
        comp = Compositor("comp")
        # ...
        gw = _StubGatewayClient()  # Never referenced
        res_server = make_resources_server(...)
        # gw is not used anywhere
    ```

    **Problems:**
    1. Confusing naming - `gw` suggests "gateway" but it's for compositor
    2. Dead code - variables created but never used
    3. Misleading comments - says "placeholder gateway client" but it's a compositor
    4. Unnecessary async context manager in Pattern 1
    5. Code smell - suggests the author wasn't sure what was needed

    **Fix:** Delete all the unused `gw`/`gw_server` variables and their creation.

    **For test_resources_list_changed_notification specifically:**
    The entire `gw_server = FastMCP("gw")` and `async with Client(gw_server) as gw:`
    block is unnecessary. The test creates its own compositor and resources server
    and doesn't need any gateway/compositor client.
  |||,
  filesToRanges={
    'adgn/tests/mcp/resources/test_notifications.py': [
      [29, 31],  // gw_server = FastMCP("gw") and unused async context manager
    ],
    'adgn/tests/mcp/resources/test_list_changes_subscriptions.py': [
      [30, 30],  // gw = _StubGatewayClient() - unused
      [53, 53],  // gw = _StubGatewayClient() - unused (second test)
    ],
    'adgn/tests/mcp/resources/test_subscriptions_index.py': [
      [51, 51],  // gw = _StubGatewayClient() - unused
    ],
  },
)
