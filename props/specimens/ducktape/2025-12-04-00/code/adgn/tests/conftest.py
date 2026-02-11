from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import asynccontextmanager, suppress
import os
from pathlib import Path
import platform
import re

import docker
from fastmcp.client import Client
from fastmcp.mcp_config import MCPConfig
from fastmcp.server import FastMCP
from openai import AsyncOpenAI
import pytest

from adgn.agent.approvals import load_default_policy_source
from adgn.agent.persist import AgentMetadata
from adgn.agent.persist.sqlite import SQLitePersistence
from adgn.agent.policies.loader import approve_all_policy_text
from adgn.agent.policies.policy_types import ApprovalDecision
from adgn.agent.runtime.images import DEFAULT_RUNTIME_IMAGE
from adgn.mcp._shared.container_session import ContainerOptions
from adgn.mcp.approval_policy.engine import PolicyEngine
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.compositor.setup import mount_standard_inproc_servers
from adgn.mcp.exec.docker.server import make_container_exec_server
from adgn.mcp.notifications.buffer import NotificationsBuffer
from adgn.mcp.stubs.typed_stubs import TypedClient
from adgn.mcp.testing.simple_servers import make_simple_mcp
from tests.support.responses import _StepRunner
from tests.support.steps import Step
from tests.support.types import McpServerSpecs


@pytest.fixture
def test_agent_id(request: pytest.FixtureRequest) -> str:
    """Generate a sanitized agent ID from the test node ID."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", request.node.nodeid) or "tests"


@pytest.fixture
async def compositor():
    """Fresh Compositor instance for each test.

    No explicit cleanup - compositor will be garbage collected after test completes.
    """
    return Compositor("comp")


# Ensure shared fixtures from tests/support are always registered, even when
# running a subset of tests or in parallel workers where the module wouldn't be
# imported implicitly.
pytest_plugins = (
    "tests.support.responses",
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
def docker_client():
    """Provide a Docker client for tests that need container operations."""
    return docker.from_env()


@pytest.fixture
async def sqlite_persistence(tmp_path):
    p = SQLitePersistence(tmp_path / "agent.sqlite")
    await p.ensure_schema()
    return p


@pytest.fixture
def make_approval_policy_server(sqlite_persistence, docker_client, test_agent_id) -> Callable[[str], PolicyEngine]:
    """Factory producing PolicyEngine instances with per-test defaults.

    The returned engine owns .reader, .proposer and .approver sub-servers.
    """

    def _make(policy_source: str, *, agent_id: str | None = None) -> PolicyEngine:
        return PolicyEngine(
            docker_client=docker_client,
            agent_id=agent_id or test_agent_id,
            persistence=sqlite_persistence,
            policy_source=policy_source,
        )

    return _make


@pytest.fixture
async def approval_policy_server(sqlite_persistence, docker_client) -> PolicyEngine:
    """PolicyEngine fixture that owns .reader, .proposer and .approver sub-servers."""
    return PolicyEngine(
        docker_client=docker_client,
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
def backend_server(make_backend_server: Callable[[str], FastMCP]) -> FastMCP:
    return make_backend_server("backend")


@pytest.fixture
def make_step_runner(responses_factory):
    """Factory fixture that creates step runners.

    Returns a factory function that creates _StepRunner instances.
    Each runner is a context manager that validates all steps completed.

    Usage:
        def test_workflow(make_step_runner):
            with make_step_runner(steps=[...]) as runner:
                # Use runner
                pass
            # Validation happens automatically on context exit

        def test_multiple_agents(make_step_runner):
            with make_step_runner(steps=[...]) as agent1, \
                 make_step_runner(steps=[...]) as agent2:
                # Use both agents
                pass
    """

    def _make(steps: Sequence[Step]) -> _StepRunner:
        return _StepRunner(factory=responses_factory, steps=steps)

    return _make


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


async def _setup_pg_compositor(
    servers: McpServerSpecs, policy_engine: PolicyEngine | None, sqlite_persistence, docker_client, agent_id: str
) -> tuple[Compositor, PolicyEngine]:
    """Shared setup for make_pg_client and make_pg_compositor."""
    comp = Compositor("comp")

    if policy_engine is None:
        # Create agent in DB first to satisfy FK constraints when recording approvals
        # Use the persistence API to create the agent properly
        agent_id = await sqlite_persistence.create_agent(mcp_config=MCPConfig(), metadata=AgentMetadata(preset="test"))

        policy_engine = PolicyEngine(
            docker_client=docker_client,
            agent_id=agent_id,
            persistence=sqlite_persistence,
            policy_source=approve_all_policy_text(),
        )

    await comp.mount_inproc("reader", policy_engine.reader)
    await _mount_servers(comp, servers)
    comp.add_middleware(policy_engine.gateway)
    await mount_standard_inproc_servers(compositor=comp, mount_resources=False)

    return comp, policy_engine


@pytest.fixture
def make_pg_client(sqlite_persistence, docker_client, test_agent_id):
    """Async helper to open a Compositor with policy gateway, yielding just the client.

    Usage:
        async with make_pg_client(servers) as client:
            result = await client.call_tool(...)

    For tests that need access to the compositor or engine, use make_pg_compositor instead.
    """

    @asynccontextmanager
    async def _open(servers: McpServerSpecs, *, policy_engine: PolicyEngine | None = None):
        comp, _ = await _setup_pg_compositor(servers, policy_engine, sqlite_persistence, docker_client, test_agent_id)
        async with Client(comp) as sess:
            yield sess

    return _open


@pytest.fixture
def make_pg_compositor(sqlite_persistence, docker_client, test_agent_id):
    """Async helper with full access to compositor and engine.

    Usage:
        async with make_pg_compositor(servers, policy_engine=engine) as (sess, comp, engine):
            ...

    For tests that only need the client, prefer make_pg_client instead.
    """

    @asynccontextmanager
    async def _open(servers: McpServerSpecs, *, policy_engine: PolicyEngine | None = None):
        comp, engine = await _setup_pg_compositor(
            servers, policy_engine, sqlite_persistence, docker_client, test_agent_id
        )
        async with Client(comp) as sess:
            yield sess, comp, engine

    return _open


# Note: legacy open_mcp_with_slots fixture has been removed. Use make_pg_client or make_pg_compositor instead.


@pytest.fixture
async def pg_client(make_pg_client, backend_server):
    """Ready-to-use client with backend_server mounted and allow-all policy.

    For tests that just need a simple compositor with a backend server.
    """
    async with make_pg_client({"backend": backend_server}) as sess:
        yield sess


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
async def pg_compositor_box(make_pg_compositor):
    """Async fixture with boxed Docker exec server and policy gateway.

    Mounts a per-session container exec server under name "box" with policy gateway.
    Yields (client, compositor, policy_engine).
    """
    server = make_container_exec_server(make_container_opts("python:3.12-slim"), name="box")
    async with make_pg_compositor({"box": server}) as result:
        yield result


@pytest.fixture
async def pg_client_box(pg_compositor_box):
    """MCP client for boxed Docker exec server (convenience extractor).

    For tests that only need the client, not the full compositor/engine.
    """
    client, _compositor, _policy_engine = pg_compositor_box
    return client


@pytest.fixture
async def pg_compositor_echo(echo_spec, make_pg_compositor):
    """Async fixture with echo server and policy gateway.

    Yields (client, compositor, policy_engine).
    """
    async with make_pg_compositor(echo_spec) as result:
        yield result


@pytest.fixture
async def pg_client_echo(pg_compositor_echo):
    """MCP client for echo server (convenience extractor).

    For tests that only need the client, not the full compositor/engine.
    """
    client, _compositor, _policy_engine = pg_compositor_echo
    return client


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
        buf = NotificationsBuffer(compositor=comp)
        async with Client(comp, message_handler=buf.handler) as sess:
            yield sess, comp, buf

    return _open


@pytest.fixture
def docker_exec_server_alpine():
    opts = make_container_opts("alpine:3.19")
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
    return make_container_exec_server(opts)


# --- Approval policy presets ------------------------------------------


def make_policy_source(decision: ApprovalDecision) -> str:
    """Generate a policy source that always returns the specified decision.

    Args:
        decision: ApprovalDecision enum value (ALLOW, ASK, DENY_CONTINUE, DENY_ABORT)
    """
    return f'''"""Policy that returns {decision.value} for all calls."""
from adgn.agent.policies.policy_types import ApprovalDecision, PolicyRequest, PolicyResponse
from adgn.agent.policies.scaffold import run

def decide(_req: PolicyRequest) -> PolicyResponse:
    return PolicyResponse(decision=ApprovalDecision.{decision.name}, rationale="{decision.value}")

if __name__ == "__main__":
    raise SystemExit(run(decide))
'''


@pytest.fixture
def make_decision_engine(
    make_approval_policy_server: Callable[[str], PolicyEngine],
) -> Callable[[ApprovalDecision], PolicyEngine]:
    """Factory for creating PolicyEngine with a specific decision policy.

    Usage:
        engine = make_decision_engine(ApprovalDecision.ALLOW)
        engine = make_decision_engine(ApprovalDecision.DENY_ABORT)
        engine = make_decision_engine(ApprovalDecision.ASK)

    Thin wrapper around make_approval_policy_server that handles policy source generation.
    """

    def _make(decision: ApprovalDecision) -> PolicyEngine:
        policy_source = make_policy_source(decision)
        return make_approval_policy_server(policy_source)

    return _make


@pytest.fixture
async def approval_policy_reader_allow_all(sqlite_persistence, docker_client) -> FastMCP:
    """Approval policy reader server with an approve-all policy program.

    Uses the packaged approve_all.py source and evaluates via Docker.
    """
    engine = PolicyEngine(
        docker_client=docker_client,
        agent_id="tests",
        persistence=sqlite_persistence,
        policy_source=approve_all_policy_text(),
    )
    return engine.reader


@pytest.fixture
def stub_policy_engine():
    """Stub policy engine for tests that don't need real policy evaluation."""

    class _StubPolicyEngine:
        def get_policy(self) -> tuple[str, int]:
            return ("# allow all\n", 1)

    return _StubPolicyEngine()


@pytest.fixture
def approval_policy_reader_stub() -> FastMCP:
    server = FastMCP("approval_policy")

    @server.tool(name="evaluate_policy")
    def _evaluate_policy(name: str, _arguments: dict | None = None) -> dict[str, str]:
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
def echo_spec(make_backend_server) -> McpServerSpecs:
    """In-proc FastMCP server spec for echo tests."""
    return {"echo": make_backend_server("echo")}
