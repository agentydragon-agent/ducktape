local I = import '../../specimens/lib.libsonnet';

// iss-063: Tests manually create resources server instead of using shared fixtures

I.issueOneOccurrence(
  rationale=|||
    Tests manually create resources servers with `make_resources_server(name="resources", compositor=comp)`
    instead of using the shared fixtures (`resources_server`, `resources_client`, `typed_resources_client`).

    **Current pattern:**
    ```python
    async def test_something():
        comp = Compositor("comp")
        # ...
        res_server = make_resources_server(name="resources", compositor=comp)
        async with Client(res_server) as client:
            rc = ResourcesClient(client)
            # ... use rc ...
    ```

    **Problems:**
    1. Duplicates resources server creation logic across tests
    2. `name="resources"` is redundant - that's the default name
    3. Doesn't use shared pytest fixtures
    4. Manually creates ResourcesClient instead of using typed fixture
    5. More boilerplate than necessary

    **Fix:**
    ```python
    async def test_something(compositor, typed_resources_client):
        # compositor and typed_resources_client are injected
        # ... use typed_resources_client directly ...
    ```

    Or if the test needs to mount specific origins first:
    ```python
    async def test_something(compositor, resources_server, resources_client):
        origin = FastMCP("origin")
        await compositor.mount_inproc("origin", origin)
        # resources_server is already connected to compositor
        rc = ResourcesClient(resources_client)
        # ... use rc ...
    ```

    **Benefits:**
    1. Uses shared fixtures - follows pytest conventions
    2. Less boilerplate - no manual server/client creation
    3. Easier to test - can mock fixtures
    4. Consistent with other tests using fixtures
    5. No redundant name parameter
  |||,
  filesToRanges={
    'adgn/tests/mcp/resources/test_list_changes_subscriptions.py': [
      [31, 31],  // make_resources_server(name="resources", compositor=comp)
      [54, 54],  // make_resources_server(name="resources", compositor=comp) - second test
    ],
    'adgn/tests/mcp/resources/test_subscriptions_index.py': [
      [52, 52],  // make_resources_server(name="resources", compositor=comp)
    ],
    'adgn/tests/mcp/test_resources_subscriptions_index.py': [
      [53, 53],  // make_resources_server(name="resources", compositor=comp)
    ],
    'adgn/tests/mcp/resources/test_notifications.py': [
      [35, 35],  // make_resources_server(name="resources", compositor=comp)
    ],
  },
)
