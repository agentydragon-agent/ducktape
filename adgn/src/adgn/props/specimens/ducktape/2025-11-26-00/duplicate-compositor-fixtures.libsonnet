local I = import '../../lib.libsonnet';

// iss-061: Duplicate Compositor test fixtures - should use shared fixtures

I.issue(
  expect_caught_from=[
    ['adgn/tests/conftest.py'],
    ['adgn/tests/mcp/conftest.py'],
    ['adgn/tests/mcp/test_chat_notifications.py'],
    ['adgn/tests/mcp/test_resources_subscriptions_index.py'],
    ['adgn/tests/mcp/resources/test_notifications.py'],
    ['adgn/tests/mcp/resources/test_subscriptions_index.py'],
    ['adgn/tests/mcp/compositor/test_pinned_unmount.py'],
    ['adgn/tests/mcp/test_stdio_notifications_envelope.py'],
    ['adgn/tests/mcp/resources/test_list_changes_subscriptions.py'],
    ['adgn/tests/mcp/resources/test_subscribe.py'],
  ],
  rationale=|||
    Tests create `Compositor("comp")` instances directly in 13 locations instead of
    using shared pytest fixtures. This violates DRY and makes it harder to mock or
    configure the compositor consistently across tests.

    **Pattern found repeatedly:**
    ```python
    async def test_something():
        comp = Compositor("comp")
        async with Client(comp) as client:
            # ... test logic ...
    ```

    **Or in fixture factories:**
    ```python
    @asynccontextmanager
    async def _open(servers: McpServerSpecs):
        comp = Compositor("comp")
        await _mount_servers(comp, servers)
        async with Client(comp) as sess:
            yield sess, comp
    ```

    **Problems:**
    1. Code duplication - same `Compositor("comp")` pattern repeated 13 times
    2. Inconsistent - some use "comp", one uses "compositor", one uses "comp2"
    3. Hard to mock - can't inject test doubles at fixture level
    4. No reuse - every test/fixture creates its own instance

    **Fix:** Create shared pytest fixtures in `conftest.py`:
    - `compositor()` fixture - returns `Compositor("comp")` with function scope
    - `compositor_client(compositor)` - yields Client session contextmanager
    - `resources_server(compositor)` - creates resources server from compositor
    - `resources_client(resources_server)` - yields resources client session

    Then replace all 13 direct `Compositor("comp")` instantiations with fixture parameters:
    ```python
    # Before: async def test_something(): comp = Compositor("comp"); ...
    # After:  async def test_something(compositor): ...
    ```

    **Benefits:**
    1. Single source of truth for test compositor creation
    2. Easy to mock/configure globally
    3. Consistent naming and setup
    4. Follows pytest best practices
    5. Matches production pattern - Compositor manages its own lifecycle without explicit cleanup
  |||,
  filesToRanges={
    'adgn/tests/conftest.py': [
      [192, 192],  // comp = Compositor("comp") in make_pg_compositor
      [228, 228],  // comp = Compositor("comp") in make_compositor
    ],
    'adgn/tests/mcp/conftest.py': [
      [41, 41],  // comp = Compositor("comp") in resources_env
    ],
    'adgn/tests/mcp/test_chat_notifications.py': [
      [21, 21],  // comp = Compositor("compositor") - inconsistent name!
    ],
    'adgn/tests/mcp/test_resources_subscriptions_index.py': [
      [47, 47],  // comp = Compositor("comp")
    ],
    'adgn/tests/mcp/resources/test_notifications.py': [
      [34, 34],  // comp = Compositor("comp")
    ],
    'adgn/tests/mcp/resources/test_subscriptions_index.py': [
      [46, 46],  // comp = Compositor("comp")
    ],
    'adgn/tests/mcp/compositor/test_pinned_unmount.py': [
      [20, 20],  // comp = Compositor("comp")
    ],
    'adgn/tests/mcp/test_stdio_notifications_envelope.py': [
      [43, 43],  // comp = Compositor("comp")
    ],
    'adgn/tests/mcp/resources/test_list_changes_subscriptions.py': [
      [26, 26],  // comp = Compositor("comp")
      [47, 47],  // comp = Compositor("comp2") - different name for second compositor
    ],
    'adgn/tests/mcp/resources/test_subscribe.py': [
      [18, 18],  // comp = Compositor("comp")
    ],
  },
)
