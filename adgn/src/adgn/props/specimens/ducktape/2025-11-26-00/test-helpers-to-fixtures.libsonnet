local I = import '../lib.libsonnet';

// iss-062: Test helper functions should be pytest fixtures

I.issue(
  snapshot='ducktape/2025-11-26-00',
  rationale=|||
    Multiple test files define helper functions (with `def _...`) that create test
    servers or resources. These are basic factories that don't depend on test-specific
    logic and should be pytest fixtures instead.

    **Pattern:**
    ```python
    def _make_origin() -> tuple[FastMCP, SubscriptionRecorder]:
        m = NotifyingFastMCP("origin")
        recorder = install_subscription_recorder(m)
        # ... configure resource ...
        return m, recorder

    async def test_something():
        origin, hooks = _make_origin()  # Called directly in test
        # ... use origin ...
    ```

    **Problems:**
    1. Functions are called directly in tests instead of using pytest's dependency injection
    2. Not reusable across test files without duplication
    3. Can't easily override or mock for specific test scenarios
    4. Doesn't follow pytest best practices for test setup

    **Fix:**
    ```python
    @pytest.fixture
    def origin_with_recorder():
        """Origin server with subscription recorder attached."""
        m = NotifyingFastMCP("origin")
        recorder = install_subscription_recorder(m)
        # ... configure resource ...
        return m, recorder

    async def test_something(origin_with_recorder):
        origin, hooks = origin_with_recorder  # Injected by pytest
        # ... use origin ...
    ```

    **Benefits:**
    1. Follows pytest conventions - clear fixture dependencies
    2. Reusable across test files via conftest.py
    3. Easy to override with fixture scope
    4. Can be parameterized using @pytest.mark.parametrize on fixtures
    5. Better test isolation and setup/teardown management

    **Affected functions:**
    - `_make_origin()` - Creates NotifyingFastMCP origin with recorder (2 occurrences)
    - `_backend()` - Creates FastMCP backend server
    - `_make_notifier()` - Creates NotifyingFastMCP instance
    - `_make_backend()` - Creates FastMCP backend server (2 occurrences)
    - `_make_server()` - Creates exec server
    - `create_chat_servers()` - Creates chat servers with shared store
    - `make_echo_server()` - Creates echo server for testing

    All these are simple factories that don't depend on test-specific state and should
    be converted to fixtures.

    **Note:** Some similar functions are already fixtures (e.g., `bus()` in test_ui_server.py)
    or take fixture parameters (e.g., `open_seatbelt_session(sqlite_persistence)`) and
    are correctly implemented. This issue only covers plain factory functions that should
    be fixtures but aren't.
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
