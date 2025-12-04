local I = import '../../lib.libsonnet';

// iss-059: Resources server should take Client, not Compositor

I.issue(
  rationale=|||
    Lines 238-241 create a `Client(compositor)` internally, but the resources server
    should receive the Client as a parameter instead of the Compositor.

    **Current pattern:**
    ```python
    def make_resources_server(name: str, compositor: Compositor) -> Server:
        # ...
        # Direct client to compositor (bypasses policy gateway to prevent double enforcement)
        compositor_client = Client(compositor)
        # ... use compositor_client ...
    ```

    **Problem:** This violates "take what you actually need" principle (Dependency
    Injection / Interface Segregation):
    1. Server receives Compositor but only uses it to create a Client
    2. Creates client internally instead of receiving it
    3. Harder to test - can't inject a mock/test client

    **Fix:**
    ```python
    def make_resources_server(name: str, client: Client) -> Server:
        """Create resources aggregator server.

        Args:
            name: Server name
            client: Direct client to compositor (should bypass policy gateway)
        """
        # ... use client directly ...
    ```

    **Caller changes:**
    ```python
    # Before:
    server = make_resources_server(name="resources", compositor=compositor)

    # After:
    client = Client(compositor)  # Or injected test client
    server = make_resources_server(name="resources", client=client)
    ```

    **Benefits:**
    1. Takes what it actually needs (client, not compositor)
    2. Easier to test - inject mock client
    3. Clearer dependencies
    4. Follows standard DI principle

    **Note:** Delete the useless comments about "bypassing policy gateway" at lines
    238-240. The parameter docstring should explain this instead.
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/resources/server.py': [
      [238, 241],  // Creates Client internally, should receive it
    ],
  },
)
