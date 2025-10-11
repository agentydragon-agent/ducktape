from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager
from importlib import resources
import os
import platform

from fastmcp.client import Client
from fastmcp.server import FastMCP
from openai import AsyncOpenAI
import pytest

from adgn.agent.approvals import ApprovalHub, ApprovalPolicyEngine, load_default_policy_source
from adgn.agent.persist.sqlite import SQLitePersistence
from adgn.mcp._shared.container_session import ContainerOptions
from adgn.mcp.approval_policy.clients import PolicyReaderClient
from adgn.mcp.approval_policy.server import ApprovalPolicyServer
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.compositor.setup import mount_standard_inproc_servers
from adgn.mcp.docker_exec.server import make_container_exec_server
from adgn.mcp.policy_gateway.middleware import install_policy_gateway

# Top-level imports for fixtures
from adgn.mcp.testing.typed_stubs import TypedClient
import docker

# Ensure shared fixtures from tests/fixtures are always registered, even when
# running a subset of tests or in parallel workers where the module wouldn't be
# imported implicitly.
pytest_plugins = [
    "tests.fixtures.responses",
    # Ensure pytest-asyncio plugin is loaded in all workers so async tests run properly
    "pytest_asyncio",
]


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("adgn")
    group.addoption(
        "--trace-ws",
        action="store_true",
        default=True,
        help="Emit detailed WS traces during tests (default: on)",
    )
    group.addoption(
        "--no-trace-ws",
        action="store_true",
        default=False,
        help="Disable WS traces added by the test helpers",
    )


def pytest_configure(config: pytest.Config) -> None:
    # Default: tracing ON unless explicitly disabled by --no-trace-ws
    if config.getoption("--no-trace-ws"):
        os.environ["ADGN_TEST_TRACE_WS"] = "0"
    else:
        os.environ["ADGN_TEST_TRACE_WS"] = "1"
    # Policy eval runs the shim as a module; require adgn installed in the image.
    # Use the runtime image built from docker/runtime/Dockerfile.
    os.environ.setdefault("ADGN_POLICY_EVAL_IMAGE", "adgn-runtime:latest")


@pytest.fixture(autouse=True)
def _per_test_agent_db(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Ensure each test gets an isolated agent SQLite DB path.

    Many agent/server tests rely on ADGN_AGENT_DB_PATH. Setting it per-test
    avoids cross-test interference when running in parallel.
    """
    monkeypatch.setenv("ADGN_AGENT_DB_PATH", str(tmp_path / "agent.sqlite"))


@pytest.fixture
async def sqlite_persistence(tmp_path):
    p = SQLitePersistence(str(tmp_path / "agent.sqlite"))
    await p.ensure_schema()
    return p


@pytest.fixture
async def approval_engine(sqlite_persistence) -> ApprovalPolicyEngine:
    return ApprovalPolicyEngine(
        docker_client=docker.from_env(),
        agent_id="tests",
        persistence=sqlite_persistence,
        policy_source=load_default_policy_source(),
    )


@pytest.fixture
def make_typed_mcp():
    """Global typed MCP helper yielding (TypedClient, session) for a FastMCP server.

    Usage:
        async with make_typed_mcp(server, name) as (client, sess):
            ...
    """

    @asynccontextmanager
    async def _open(server: FastMCP, name: str):
        async with Client(server) as sess:
            client = TypedClient.from_server(server, sess)
            yield client, sess

    return _open


@pytest.fixture
def approval_hub() -> ApprovalHub:
    """Fresh ApprovalHub per test for middleware gating flows."""
    return ApprovalHub()


@pytest.fixture
def make_pg_compositor(approval_hub: ApprovalHub):
    """Async helper to open a Compositor with policy gateway middleware.

    Usage:
        async with make_pg_compositor(backend, evaluator, hub=..., notifier=...) as (sess, comp):
            ...
    """

    @asynccontextmanager
    async def _open(
        servers: dict[str, FastMCP],
        *,
        notifier=None,
    ):
        comp = Compositor("comp")
        # Mount all provided servers under the compositor
        for name, srv in servers.items():
            if not isinstance(srv, FastMCP):
                raise TypeError(f"invalid server for {name!r}: {type(srv).__name__}")
            await comp.mount_inproc(name, srv)
        # Install policy gateway with managed reader client; approval_policy is required
        reader = servers.get("approval_policy")
        if reader is None:
            raise RuntimeError("approval_policy server required for policy gateway tests")
        from fastmcp.client import Client as _Client

        stack = AsyncExitStack()
        await stack.__aenter__()
        try:
            _reader_client = await stack.enter_async_context(_Client(reader))
            policy_reader = PolicyReaderClient(_reader_client)
            install_policy_gateway(
                comp,
                hub=approval_hub,
                policy_reader=policy_reader,
                pending_notifier=notifier,
            )
            # Mount standard in-proc servers (meta + admin pinned; no resources without gateway client)
            await mount_standard_inproc_servers(compositor=comp, gateway_client=None)
            async with Client(comp) as sess:
                yield sess, comp
        finally:
            await stack.aclose()

    return _open


# Note: legacy open_mcp_with_slots fixture has been removed. Use make_pg_compositor instead.


@pytest.fixture
def make_compositor():
    """Async helper to open a Compositor and yield (Client, Compositor).

    Usage:
        async with make_compositor({"name": server, ...}) as (client, comp):
            ...
    """

    @asynccontextmanager
    async def _open(servers: dict[str, FastMCP]):
        comp = Compositor("comp")
        for name, srv in servers.items():
            if not isinstance(srv, FastMCP):
                raise TypeError(f"invalid server for {name!r}: {type(srv).__name__}")
            await comp.mount_inproc(name, srv)
        async with Client(comp) as sess:
            yield sess, comp

    return _open


@pytest.fixture
def make_pg_compositor_box(approval_policy_reader_allow_all, make_pg_compositor):
    """Helper to open a Compositor with a boxed Docker exec server and policy.

    Mounts a per-session container exec server under name "box" and mounts the
    approval_policy reader. Yields (client, compositor).
    """

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _open():
        server = make_container_exec_server(
            ContainerOptions(
                image="python:3.12-slim",
                working_dir="/workspace",
                volumes=None,
                describe=True,
                ephemeral=True,
            ),
            server_name="box",
        )
        async with make_pg_compositor(
            {"box": server, "approval_policy": approval_policy_reader_allow_all}
        ) as pair:
            yield pair

    return _open


@pytest.fixture
def make_pg_compositor_echo(make_echo_spec, approval_policy_reader_allow_all, make_pg_compositor):
    """Helper to open a Compositor with the echo server and policy mounted.

    Yields (client, compositor).
    """

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _open():
        specs = make_echo_spec()
        servers = {**specs(), "approval_policy": approval_policy_reader_allow_all}
        async with make_pg_compositor(servers) as pair:
            yield pair

    return _open


@pytest.fixture
async def pg_compositor_echo(make_pg_compositor_echo):
    """Async fixture yielding (client, compositor) with echo + approval mounted.

    Convenience wrapper around make_pg_compositor_echo() so tests can depend on a
    ready session without using an explicit async with.
    """
    async with make_pg_compositor_echo() as pair:
        yield pair


@pytest.fixture
def make_buffered_client():
    """Async helper to open a Compositor + Client with NotificationsBuffer.

    Yields (client, compositor, buffer) so tests can read buffered notifications
    or pass buffer.poll into handlers.
    """

    @asynccontextmanager
    async def _open(servers: dict[str, FastMCP]):
        comp = Compositor("comp")
        for name, srv in servers.items():
            if not isinstance(srv, FastMCP):
                raise TypeError(f"invalid server for {name!r}: {type(srv).__name__}")
            await comp.mount_inproc(name, srv)
        from adgn.mcp.notifications.buffer import NotificationsBuffer

        buf = NotificationsBuffer(compositor=comp)
        async with Client(comp, message_handler=buf.handler) as sess:
            yield sess, comp, buf

    return _open


@pytest.fixture
def docker_exec_server_alpine():
    opts = ContainerOptions(
        image="alpine:3.19",
        working_dir="/workspace",
        volumes=None,
        describe=True,
        ephemeral=True,
    )
    # Expose the tool under name expected by docker exec tests
    from adgn.mcp.docker_exec.server import make_container_exec_server

    return make_container_exec_server(opts, tool_exec_name="docker_exec")


@pytest.fixture
def docker_inproc_spec_alpine():
    opts = ContainerOptions(
        image="alpine:3.19",
        working_dir="/workspace",
        volumes=None,
        describe=True,
        ephemeral=True,
    )
    server = make_container_exec_server(opts)
    return server


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
        ephemeral=True,
    )
    from adgn.mcp.docker_exec.server import make_container_exec_server

    server = make_container_exec_server(opts)
    return server


# --- Approval policy reader presets ------------------------------------------


@pytest.fixture
async def approval_policy_reader_allow_all(sqlite_persistence) -> FastMCP:
    """Approval policy reader server with an approve-all policy program.

    Uses the packaged approve_all.py source and evaluates via Docker.
    """
    policy_text = (
        resources.files("adgn.agent.policies")
        .joinpath("approve_all.py")
        .read_text(encoding="utf-8")
    )
    eng = ApprovalPolicyEngine(
        docker_client=docker.from_env(),
        agent_id="tests",
        persistence=sqlite_persistence,
        policy_source=policy_text,
    )
    return ApprovalPolicyServer(eng)


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
    """Return a factory that yields a runtime slot spec map for an echo MCP.

    Uses in-proc embedding via make_inproc_slot_spec and attaches through the
    TestClient portal, avoiding HTTP JSON rehydration.
    """

    def _spec() -> dict[str, object]:
        from adgn.mcp.echo.server import make_echo_server

        server = make_echo_server("echo")
        return {"echo": server}

    return _spec
