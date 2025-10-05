from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager
import os
import platform

from mcp.server.fastmcp import FastMCP
from openai import AsyncOpenAI
import pytest

from adgn.mcp._shared.container_session import ContainerOptions
from adgn.mcp.docker_exec.server import make_container_exec_mcp
from adgn.mcp.inproc_transport import make_inproc_slot_spec

# Top-level imports for fixtures
from adgn.mcp.testing.typed_stubs import TypedClient

# Ensure shared fixtures from tests/fixtures are always registered, even when
# running a subset of tests or in parallel workers where the module wouldn't be
# imported implicitly.
pytest_plugins = [
    "tests.fixtures.responses",
    # Ensure pytest-asyncio plugin is loaded in all workers so async tests run properly
    "pytest_asyncio",
]


@pytest.fixture(autouse=True)
def _per_test_agent_db(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Ensure each test gets an isolated agent SQLite DB path.

    Many agent/server tests rely on ADGN_AGENT_DB_PATH. Setting it per-test
    avoids cross-test interference when running in parallel.
    """
    monkeypatch.setenv("ADGN_AGENT_DB_PATH", str(tmp_path / "agent.sqlite"))


@pytest.fixture
def make_typed_mcp():
    """Global typed MCP helper yielding (TypedClient, session) for a FastMCP server.

    Usage:
        async with make_typed_mcp(server, name) as (client, sess):
            ...
    """

    @asynccontextmanager
    async def _open(server: FastMCP, name: str):
        async with AsyncExitStack() as stack:
            spec = make_inproc_slot_spec(server)
            slot = await spec.open(stack)
            sess = slot.session
            client = TypedClient.from_server(server, sess)
            yield client, sess

    return _open


@pytest.fixture
def docker_exec_server_alpine():
    opts = ContainerOptions(
        image="alpine:3.19",
        working_dir="/workspace",
        volumes=None,
        describe=True,
    )
    return make_container_exec_mcp(opts)


@pytest.fixture
def docker_inproc_spec_alpine():
    opts = ContainerOptions(
        image="alpine:3.19",
        working_dir="/workspace",
        volumes=None,
        describe=True,
    )
    server = make_container_exec_mcp(opts)
    return make_inproc_slot_spec(server)


# --- Compatibility / opt-in fixtures used across suites ---


@pytest.fixture
def live_openai(request):
    """Provide a live AsyncOpenAI client for tests marked with `live_llm`.

    - For non-`live_llm` tests that include this fixture in the signature but
      do not actually use it (e.g., parameterized tests with a mock branch),
      return a lightweight no-op placeholder to avoid network work and keep
      those tests running.
    - For `live_llm` tests, require OPENAI_API_KEY and construct AsyncOpenAI;
      skip if the key is not available.
    """
    if request.node.get_closest_marker("live_llm") is not None:
        if not os.getenv("OPENAI_API_KEY"):
            pytest.skip("OPENAI_API_KEY not set; skipping live LLM test")
        return AsyncOpenAI()

    class _Noop:
        pass

    return _Noop()


@pytest.fixture
def docker_inproc_spec_py312():
    """Alias expected by some tests: in-proc spec backed by Python 3.12 image."""
    opts = ContainerOptions(
        image="python:3.12-alpine",
        working_dir="/workspace",
        volumes=None,
        describe=True,
    )
    server = make_container_exec_mcp(opts)
    return make_inproc_slot_spec(server)


@pytest.fixture
def require_sandbox_exec():
    """Gate shell sandbox tests to supported platforms.

    These tests exercise macOS sandbox profiles; skip on non-macOS hosts.
    """
    if platform.system() != "Darwin":
        pytest.skip("sandboxer tests require macOS host")
    return True


# --- Shared lightweight fixtures used across agent and MCP tests ---


@pytest.fixture
def make_echo_spec() -> callable:
    """Return a factory that yields a typed, JSON-serializable inproc spec for echo MCP.

    Using a typed InprocFactorySpec avoids needing TestClient.portal bridging in tests.
    """

    def _spec() -> dict[str, object]:
        from adgn.agent.runtime.specs import InprocFactorySpec

        return {"echo": InprocFactorySpec(factory="adgn.mcp.echo.server:make_echo_mcp")}

    return _spec
