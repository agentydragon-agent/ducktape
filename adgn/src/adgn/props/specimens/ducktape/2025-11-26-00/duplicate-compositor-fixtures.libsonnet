local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale=|||
    Eight test files create Compositor instances directly (e.g., `comp = Compositor("comp")`)
    instead of using shared pytest fixtures. Occurrences in test_chat_notifications.py,
    test_resources_subscriptions_index.py, test_notifications.py, test_subscriptions_index.py,
    test_pinned_unmount.py, test_stdio_notifications_envelope.py,
    test_list_changes_subscriptions.py (creates two: "comp" and "comp2"),
    test_subscribe.py.

    Problems: Code duplication across test files, inconsistent naming (most use "comp",
    one uses "compositor", one uses "comp2"), hard to mock (can't inject test doubles
    at fixture level), no reuse (every test creates own instance).

    Use shared pytest fixtures. Benefits: single source of truth for test compositor
    creation, easy to mock/configure globally, consistent naming and setup, follows
    pytest best practices.
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
