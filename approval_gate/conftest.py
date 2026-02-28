"""pytest configuration for approval_gate tests."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest

# Patch FastMCP._docket_lifespan to a no-op for all tests in this package.
#
# FastMCP's default _docket_lifespan creates a Docket + Worker connected to an
# in-memory FakeServer (memory:// URL). The FakeServer is stored in a module-level
# dict (docket._redis._memory_servers) and is shared across tests. Between tests,
# the FakeServer accumulates stale asyncio state (pubsub subscriptions, connection
# pools) from the previous test's event loop. When a new event loop is used in the
# next test, the stale state causes the Worker's _cancellation_listener to hang
# (waiting for _cancellation_ready which is never set), blocking server startup for
# > 10 seconds and triggering the _serve() timeout.
#
# Patching at module load time is the most reliable approach: it applies before any
# fixture setup, regardless of async fixture loop scope or fixture ordering.
#
# ApprovalGateServer already overrides _docket_lifespan in proxy_server.py, so this
# patch only affects bare FastMCP instances (like the test's backend_server fixture).
from fastmcp.server.server import FastMCP

from approval_gate.storage import ActionStorage


@asynccontextmanager
async def _noop_docket_lifespan(self: FastMCP):
    yield


FastMCP._docket_lifespan = _noop_docket_lifespan  # type: ignore[method-assign]


def pytest_configure(config: pytest.Config) -> None:
    """Configure pytest-asyncio to auto mode with function-scoped event loops."""
    config.addinivalue_line("markers", "asyncio: mark test as async")
    config.option.asyncio_mode = "auto"
    # Ensure each test gets its own event loop. The default (None → session scope)
    # causes all tests to share one loop, leading to cross-test contamination when
    # one test's background tasks or anyio cancel scopes outlive the test.
    # config.override_ini is only available from pytest 9.1+; for 9.0.x we write
    # directly to _inicache, which getini() consults on every subsequent call.
    config._inicache["asyncio_default_fixture_loop_scope"] = "function"


@pytest.fixture
async def storage(tmp_path: Path) -> ActionStorage:
    """Temporary in-memory storage for tests."""
    return await ActionStorage.initialize(tmp_path / "test.db")
