local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale=|||
    Tests create `Compositor("comp")` instances directly instead of using shared
    pytest fixtures. This violates DRY and makes it harder to mock or configure
    the compositor consistently across tests.

    **Pattern found repeatedly:**
    ```python
    async def test_something():
        comp = Compositor("comp")
        async with Client(comp) as client:
            # ... test logic ...
    ```

    **Problems:**
    1. Code duplication - same pattern repeated across test files
    2. Inconsistent - some use "comp", one uses "compositor", one uses "comp2"
    3. Hard to mock - can't inject test doubles at fixture level
    4. No reuse - every test creates its own instance

    **Fix:** Use shared pytest fixtures (or create them if they don't exist):
    ```python
    # Before: async def test_something(): comp = Compositor("comp"); ...
    # After:  async def test_something(compositor): ...
    ```

    Note: Conftest files that create Compositor instances within fixture factories
    are fine - that's their job. The issue is test files that should be using
    fixtures but aren't.

    **Benefits:**
    1. Single source of truth for test compositor creation
    2. Easy to mock/configure globally
    3. Consistent naming and setup
    4. Follows pytest best practices
  |||,
  occurrences=[
    {
      files: {
        'adgn/tests/mcp/test_chat_notifications.py': [21],
      },
      note: 'Creates Compositor("compositor") - inconsistent name',
      expect_caught_from: [['adgn/tests/mcp/test_chat_notifications.py']],
    },
    {
      files: {
        'adgn/tests/mcp/test_resources_subscriptions_index.py': [47],
      },
      note: 'Creates Compositor("comp") directly',
      expect_caught_from: [['adgn/tests/mcp/test_resources_subscriptions_index.py']],
    },
    {
      files: {
        'adgn/tests/mcp/resources/test_notifications.py': [34],
      },
      note: 'Creates Compositor("comp") directly',
      expect_caught_from: [['adgn/tests/mcp/resources/test_notifications.py']],
    },
    {
      files: {
        'adgn/tests/mcp/resources/test_subscriptions_index.py': [46],
      },
      note: 'Creates Compositor("comp") directly',
      expect_caught_from: [['adgn/tests/mcp/resources/test_subscriptions_index.py']],
    },
    {
      files: {
        'adgn/tests/mcp/compositor/test_pinned_unmount.py': [20],
      },
      note: 'Creates Compositor("comp") directly',
      expect_caught_from: [['adgn/tests/mcp/compositor/test_pinned_unmount.py']],
    },
    {
      files: {
        'adgn/tests/mcp/test_stdio_notifications_envelope.py': [43],
      },
      note: 'Creates Compositor("comp") directly',
      expect_caught_from: [['adgn/tests/mcp/test_stdio_notifications_envelope.py']],
    },
    {
      files: {
        'adgn/tests/mcp/resources/test_list_changes_subscriptions.py': [26, 47],
      },
      note: 'Creates two Compositor instances ("comp" and "comp2")',
      expect_caught_from: [['adgn/tests/mcp/resources/test_list_changes_subscriptions.py']],
    },
    {
      files: {
        'adgn/tests/mcp/resources/test_subscribe.py': [18],
      },
      note: 'Creates Compositor("comp") directly',
      expect_caught_from: [['adgn/tests/mcp/resources/test_subscribe.py']],
    },
  ],
)
