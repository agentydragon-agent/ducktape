from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager, suppress
from importlib import resources
import os
from pathlib import Path
import platform
import re

import docker
from fastmcp.client import Client
from fastmcp.server import FastMCP
from openai import AsyncOpenAI
import pytest

from adgn.agent.approvals import ApprovalPolicyEngine, load_default_policy_source
from adgn.agent.persist.sqlite import SQLitePersistence
from adgn.agent.runtime.images import DEFAULT_RUNTIME_IMAGE
from adgn.mcp._shared.container_session import ContainerOptions
from adgn.mcp.approval_policy.engine import PolicyEngine
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.compositor.setup import mount_standard_inproc_servers
from adgn.mcp.exec.docker.server import make_container_exec_server
from adgn.mcp.stubs.typed_stubs import TypedClient
from adgn.mcp.testing.simple_servers import make_simple_mcp
from tests.types import McpServerSpecs

# Ensure shared fixtures from tests/fixtures are always registered, even when
# running a subset of tests or in parallel workers where the module wouldn't be
# imported implicitly.
pytest_plugins = (
    "tests.fixtures.responses",
    "pytest_asyncio",  # Ensure async fixtures work in worker processes
)


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("adgn")
    group.addoption(
        "--trace-ws", action="store_true", default=True, help="Emit detailed WS traces during tests (default: on)"
    )
    group.addoption(
        "--no-trace-ws", action="store_true", default=False, help="Disable WS traces added by the test helpers"
    )


def pytest_configure(config: pytest.Config) -> None:
    # Default: tracing ON unless explicitly disabled by --no-trace-ws
    if config.getoption("--no-trace-ws"):
        os.environ["ADGN_TEST_TRACE_WS"] = "0"
    else:
        os.environ["ADGN_TEST_TRACE_WS"] = "1"
    # Ensure runtime/policy evaluation containers use a single image tag.
    os.environ.setdefault("ADGN_RUNTIME_IMAGE", DEFAULT_RUNTIME_IMAGE)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        if item.get_closest_marker("requires_sandbox_exec") is not None:
            item.add_marker(pytest.mark.macos)


def pytest_runtest_setup(item: pytest.Item) -> None:
    if item.get_closest_marker("requires_sandbox_exec") is not None and platform.system() != "Darwin":
        pytest.skip("seatbelt sandbox tests require macOS (sandbox-exec unavailable)")
    if item.get_closest_marker("macos") is not None and platform.system() != "Darwin":
        pytest.skip("macOS-only test")
    if item.get_closest_marker("requires_docker") is None:
        return
    try:
        client = docker.from_env()
        client.ping()
    except docker.errors.DockerException as exc:
        pytest.skip(f"Docker not available: {exc}")
    else:
        with suppress(Exception):
            client.close()


@pytest.fixture(autouse=True)
def _per_test_agent_db(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Ensure each test gets an isolated agent SQLite DB path.

    Many agent/server tests rely on ADGN_AGENT_DB_PATH. Setting it per-test
    avoids cross-test interference when running in parallel.
    """
    monkeypatch.setenv("ADGN_AGENT_DB_PATH", str(tmp_path / "agent.sqlite"))


@pytest.fixture
async def sqlite_persistence(tmp_path):
    p = SQLitePersistence(tmp_path / "agent.sqlite")
    await p.ensure_schema()
    return p


@pytest.fixture
def make_policy_engine(sqlite_persistence, request: pytest.FixtureRequest):
    """Factory producing ApprovalPolicyEngine instances with per-test defaults."""

    def _make(policy_source: str, *, agent_id: str | None = None) -> ApprovalPolicyEngine:
        default_id = re.sub(r"[^a-zA-Z0-9_-]", "_", request.node.nodeid) or "tests"
        effective_id = agent_id or default_id
        return ApprovalPolicyEngine(
            docker_client=docker.from_env(),
            agent_id=effective_id,
            persistence=sqlite_persistence,
            policy_source=policy_source,
        )

    return _make


@pytest.fixture
async def approval_engine(sqlite_persistence) -> ApprovalPolicyEngine:
    """DEPRECATED: Use approval_policy_server fixture instead."""
    return ApprovalPolicyEngine(
        docker_client=docker.from_env(),
        agent_id="tests",
        persistence=sqlite_persistence,
        policy_source=load_default_policy_source(),
    )


@pytest.fixture
def make_approval_policy_server(sqlite_persistence, request: pytest.FixtureRequest):
    """Factory producing PolicyEngine instances with per-test defaults.

    The returned engine owns .reader, .proposer and .approver sub-servers.
    """

    def _make(policy_source: str, *, agent_id: str | None = None) -> PolicyEngine:
        default_id = re.sub(r"[^a-zA-Z0-9_-]", "_", request.node.nodeid) or "tests"
        effective_id = agent_id or default_id
        return PolicyEngine(
            docker_client=docker.from_env(),
            agent_id=effective_id,
            persistence=sqlite_persistence,
            policy_source=policy_source,
        )

    return _make


@pytest.fixture
async def approval_policy_server(sqlite_persistence) -> PolicyEngine:
    """PolicyEngine fixture that owns .reader, .proposer and .approver sub-servers."""
    return PolicyEngine(
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
def make_backend_server() -> Callable[[str], FastMCP]:
    """Factory for lightweight FastMCP backends used across tests."""

    return make_simple_mcp


@pytest.fixture
def backend_server(make_backend_server) -> FastMCP:
    return make_backend_server()


async def _mount_servers(comp: Compositor, servers: McpServerSpecs) -> None:
    """Mount all servers from McpServerSpecs dict onto a compositor.

    Validates that all servers are FastMCP instances and mounts them in-process.

    Args:
        comp: Compositor instance to mount servers on
        servers: Dict of server name -> FastMCP instance

    Raises:
        TypeError: If any server is not a FastMCP instance
    """
    for name, srv in servers.items():
        if not isinstance(srv, FastMCP):
            raise TypeError(f"invalid server for {name!r}: {type(srv).__name__}")
        await comp.mount_inproc(name, srv)


@pytest.fixture
def make_pg_client(sqlite_persistence, request: pytest.FixtureRequest):
    """Async helper to open a Compositor with policy gateway, yielding just the client.

    Usage:
        async with make_pg_client(servers) as client:
            result = await client.call_tool(...)

    For tests that need access to the compositor or engine, use make_pg_compositor instead.
    """
    from importlib import resources as pkg_resources

    @asynccontextmanager
    async def _open(servers: McpServerSpecs, *, policy_engine: PolicyEngine | None = None):
        comp = Compositor("comp")

        # If no engine provided, create one with allow-all policy
        if policy_engine is None:
            policy_text = pkg_resources.files("adgn.agent.policies").joinpath("approve_all.py").read_text(encoding="utf-8")
            default_id = re.sub(r"[^a-zA-Z0-9_-]", "_", request.node.nodeid) or "tests"
            policy_engine = PolicyEngine(
                docker_client=docker.from_env(),
                agent_id=default_id,
                persistence=sqlite_persistence,
                policy_source=policy_text,
            )

        # Mount the policy engine's reader on compositor
        await comp.mount_inproc("reader", policy_engine.reader)

        # Mount other provided servers
        await _mount_servers(comp, servers)

        # Install policy gateway middleware from the engine
        comp.add_middleware(policy_engine.gateway)

        # Mount standard in-proc servers (meta + admin pinned; no resources without gateway client)
        await mount_standard_inproc_servers(compositor=comp, mount_resources=False)
        async with Client(comp) as sess:
            yield sess

    return _open


@pytest.fixture
def make_pg_compositor(make_pg_client, sqlite_persistence, request: pytest.FixtureRequest):
    """Async helper with full access to compositor and engine.

    Usage:
        async with make_pg_compositor(servers, policy_engine=engine) as (sess, comp, engine):
            ...

    For tests that only need the client, prefer make_pg_client instead.
    """
    from importlib import resources as pkg_resources

    @asynccontextmanager
    async def _open(servers: McpServerSpecs, *, policy_engine: PolicyEngine | None = None):
        comp = Compositor("comp")

        # If no engine provided, create one with allow-all policy
        if policy_engine is None:
            policy_text = pkg_resources.files("adgn.agent.policies").joinpath("approve_all.py").read_text(encoding="utf-8")
            default_id = re.sub(r"[^a-zA-Z0-9_-]", "_", request.node.nodeid) or "tests"
            policy_engine = PolicyEngine(
                docker_client=docker.from_env(),
                agent_id=default_id,
                persistence=sqlite_persistence,
                policy_source=policy_text,
            )

        # Mount the policy engine's reader on compositor
        await comp.mount_inproc("reader", policy_engine.reader)

        # Mount other provided servers
        await _mount_servers(comp, servers)

        # Install policy gateway middleware from the engine
        comp.add_middleware(policy_engine.gateway)

        # Mount standard in-proc servers (meta + admin pinned; no resources without gateway client)
        await mount_standard_inproc_servers(compositor=comp, mount_resources=False)
        async with Client(comp) as sess:
            yield sess, comp, policy_engine

    return _open


# Note: legacy open_mcp_with_slots fixture has been removed. Use make_pg_client or make_pg_compositor instead.


@pytest.fixture
def make_compositor():
    """Async helper to open a Compositor and yield (Client, Compositor).

    Usage:
        async with make_compositor({"name": server, ...}) as (client, comp):
            ...
    """

    @asynccontextmanager
    async def _open(servers: McpServerSpecs):
        comp = Compositor("comp")
        await _mount_servers(comp, servers)
        async with Client(comp) as sess:
            yield sess, comp

    return _open


@pytest.fixture
def make_pg_compositor_box(make_pg_compositor):
    """Helper to open a Compositor with a boxed Docker exec server and policy.

    Mounts a per-session container exec server under name "box" with policy gateway.
    Yields (client, compositor, policy_engine).
    """

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _open():
        server = make_container_exec_server(make_container_opts("python:3.12-slim"), name="box")
        async with make_pg_compositor({"box": server}) as result:
            yield result

    return _open


@pytest.fixture
def make_pg_compositor_echo(make_echo_spec, make_pg_compositor):
    """Helper to open a Compositor with the echo server and policy mounted.

    Yields (client, compositor, policy_engine).
    """

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _open():
        spec_factory = make_echo_spec
        servers = spec_factory()
        async with make_pg_compositor(servers) as result:
            yield result

    return _open


@pytest.fixture
async def pg_compositor_echo(make_pg_compositor_echo):
    """Async fixture yielding (client, compositor, policy_engine) with echo + policy mounted.

    Convenience wrapper around make_pg_compositor_echo() so tests can depend on a
    ready session without using an explicit async with.
    """
    async with make_pg_compositor_echo() as result:
        yield result


@pytest.fixture
def make_buffered_client():
    """Async helper to open a Compositor + Client with NotificationsBuffer.

    Yields (client, compositor, buffer) so tests can read buffered notifications
    or pass buffer.poll into handlers.
    """

    @asynccontextmanager
    async def _open(servers: McpServerSpecs):
        comp = Compositor("comp")
        await _mount_servers(comp, servers)
        from adgn.mcp.notifications.buffer import NotificationsBuffer

        buf = NotificationsBuffer(compositor=comp)
        async with Client(comp, message_handler=buf.handler) as sess:
            yield sess, comp, buf

    return _open


@pytest.fixture
def docker_exec_server_alpine():
    opts = make_container_opts("alpine:3.19")
    # Expose the tool under name expected by docker exec tests
    from adgn.mcp.exec.docker.server import make_container_exec_server

    return make_container_exec_server(opts, tool_exec_name="docker_exec")


@pytest.fixture
def docker_inproc_spec_alpine():
    opts = make_container_opts("alpine:3.19")
    return make_container_exec_server(opts)


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
    opts = make_container_opts("python:3.12-alpine")
    from adgn.mcp.exec.docker.server import make_container_exec_server

    return make_container_exec_server(opts)


# --- Approval policy reader presets ------------------------------------------


@pytest.fixture
async def approval_policy_reader_allow_all(sqlite_persistence) -> FastMCP:
    """Approval policy reader server with an approve-all policy program.

    Uses the packaged approve_all.py source and evaluates via Docker.
    """
    policy_text = resources.files("adgn.agent.policies").joinpath("approve_all.py").read_text(encoding="utf-8")
    engine = PolicyEngine(
        docker_client=docker.from_env(), agent_id="tests", persistence=sqlite_persistence, policy_source=policy_text
    )
    return engine.reader


@pytest.fixture
def stub_approval_policy_engine():
    class _StubApprovalPolicyEngine:
        def get_policy(self) -> tuple[str, int]:
            return ("# allow all\n", 1)

    return _StubApprovalPolicyEngine()


@pytest.fixture
def approval_policy_reader_stub() -> FastMCP:
    server = FastMCP("approval_policy")

    @server.tool(name="evaluate_policy")
    def _evaluate_policy(name: str, arguments: dict | None = None) -> dict[str, str]:
        return {"decision": "allow", "rationale": "stub"}

    return server


@pytest.fixture
def require_sandbox_exec():
    """Gate shell sandbox tests to supported platforms.

    These tests exercise macOS sandbox profiles; skip on non-macOS hosts.
    """
    if platform.system() != "Darwin":
        pytest.skip("sandboxer tests require macOS host")
    return True


# --- Helper functions for container configuration ---


def make_container_opts(image: str, *, working_dir: str = "/workspace", ephemeral: bool = True) -> ContainerOptions:
    """Create standard ContainerOptions with proper Path type conversion."""
    return ContainerOptions(
        image=image, working_dir=Path(working_dir), volumes=None, describe=True, ephemeral=ephemeral
    )


# --- Shared lightweight fixtures used across agent and MCP tests ---


@pytest.fixture
def make_echo_spec(make_backend_server) -> Callable[[], McpServerSpecs]:
    """Return a factory that produces in-proc FastMCP servers for echo tests."""

    def _spec() -> McpServerSpecs:
        return {"echo": make_backend_server("echo")}

    return _spec
