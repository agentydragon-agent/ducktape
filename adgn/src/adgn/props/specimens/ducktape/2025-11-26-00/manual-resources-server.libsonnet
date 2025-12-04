local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale=|||
    Tests manually create resources servers with `make_resources_server(name="resources", compositor=comp)`
    instead of using shared pytest fixtures (`resources_server`, `resources_client`, `typed_resources_client`).

    **Problems:**
    1. Duplicates resources server creation logic across tests
    2. `name="resources"` is redundant - that's the default name
    3. Doesn't use shared pytest fixtures
    4. Manually creates ResourcesClient instead of using typed fixture
    5. More boilerplate than necessary

    **Benefits of using fixtures:**
    1. Follows pytest conventions
    2. Less boilerplate - no manual server/client creation
    3. Easier to test - can mock fixtures
    4. Consistent with other tests using fixtures
    5. No redundant name parameter
  |||,
  occurrences=[
    {
      files: {
        'adgn/tests/mcp/resources/test_list_changes_subscriptions.py': [31, 54],
      },
      note: 'Two tests manually create resources server with make_resources_server',
      expect_caught_from: [['adgn/tests/mcp/resources/test_list_changes_subscriptions.py']],
    },
    {
      files: {
        'adgn/tests/mcp/resources/test_subscriptions_index.py': [52],
      },
      note: 'Test manually creates resources server with make_resources_server',
      expect_caught_from: [['adgn/tests/mcp/resources/test_subscriptions_index.py']],
    },
    {
      files: {
        'adgn/tests/mcp/test_resources_subscriptions_index.py': [53],
      },
      note: 'Test manually creates resources server with make_resources_server',
      expect_caught_from: [['adgn/tests/mcp/test_resources_subscriptions_index.py']],
    },
    {
      files: {
        'adgn/tests/mcp/resources/test_notifications.py': [35],
      },
      note: 'Test manually creates resources server with make_resources_server',
      expect_caught_from: [['adgn/tests/mcp/resources/test_notifications.py']],
    },
  ],
)
