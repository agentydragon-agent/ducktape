local I = import '../../lib.libsonnet';


I.issue(
  expect_caught_from=[
    ['adgn/tests/mcp/test_resources_subscriptions_index.py'],
    ['adgn/tests/mcp/resources/test_subscriptions_index.py'],
    ['adgn/tests/mcp/compositor/test_pinned_unmount.py'],
    ['adgn/tests/mcp/test_notifications_envelope.py'],
    ['adgn/tests/mcp/compositor/test_meta_inproc_proxies.py'],
    ['adgn/tests/mcp/compositor/test_admin_client.py'],
    ['adgn/tests/mcp/exec/test_docker_unit.py'],
    ['adgn/tests/mcp/test_chat_server.py'],
    ['adgn/tests/mcp/test_mcp_flat_model_helper.py'],
  ],
  rationale=|||
    Multiple test files define helper functions (`def _...`) that create test servers or
    resources. These basic factories should be pytest fixtures instead of directly-called
    functions.

    **Pattern:** Functions like `_make_origin()`, `_backend()`, `_make_server()` are called
    directly in tests instead of using pytest's dependency injection.

    **Problems:**
    1. Called directly instead of using pytest's dependency injection
    2. Not reusable across test files without duplication
    3. Can't easily override or mock for specific test scenarios
    4. Doesn't follow pytest best practices

    **Fix:** Convert to `@pytest.fixture` decorated functions. Tests receive them as
    parameters instead of calling directly. Benefits: follows pytest conventions, reusable
    via conftest.py, easy to override with fixture scope, can be parameterized, better
    test isolation.

    **Affected functions across 9 files:** `_make_origin()` (2x), `_backend()`, `_make_notifier()`,
    `_make_backend()` (2x), `_make_server()`, `create_chat_servers()`, `make_echo_server()`.
    Note: some similar functions are already fixtures (e.g., `bus()` in test_ui_server.py)
    or take fixture parameters and are correctly implemented.
  |||,
  filesToRanges={
    'adgn/tests/mcp/test_resources_subscriptions_index.py': [
      [31, 42],  // def _make_origin() - creates origin with recorder
    ],
    'adgn/tests/mcp/resources/test_subscriptions_index.py': [
      [31, 43],  // def _make_origin() - duplicate definition
    ],
    'adgn/tests/mcp/compositor/test_pinned_unmount.py': [
      [9, 16],  // def _backend() - creates FastMCP backend
    ],
    'adgn/tests/mcp/test_notifications_envelope.py': [
      [9, 26],  // def _make_notifier() - creates NotifyingFastMCP
    ],
    'adgn/tests/mcp/compositor/test_meta_inproc_proxies.py': [
      [11, 18],  // def _make_backend() - creates FastMCP backend
    ],
    'adgn/tests/mcp/compositor/test_admin_client.py': [
      [8, 15],  // def _make_backend() - duplicate definition
    ],
    'adgn/tests/mcp/exec/test_docker_unit.py': [
      [10, 12],  // def _make_server() - creates exec server
    ],
    'adgn/tests/mcp/test_chat_server.py': [
      [23, 29],  // def create_chat_servers() - creates chat servers with shared store
    ],
    'adgn/tests/mcp/test_mcp_flat_model_helper.py': [
      [23, 31],  // def make_echo_server() - creates echo server for testing
    ],
  },
)
