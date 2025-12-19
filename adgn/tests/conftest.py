from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from contextlib import asynccontextmanager, suppress
import os
from pathlib import Path
import platform
import re
from unittest.mock import MagicMock

import aiodocker
import docker  # Only used for pytest_runtest_setup health check (sync hook)
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
from adgn.agent.runtime.container import AgentContainerCompositor
from adgn.agent.runtime.images import DEFAULT_RUNTIME_IMAGE
from adgn.mcp._shared.container_session import ContainerOptions
from adgn.testing.claude_code_web import get_claude_code_web_env, get_test_network_mode
from adgn.mcp.approval_policy.engine import PolicyEngine
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.enhanced.flat_mixin import FlatModelMixin
from adgn.mcp.exec.docker.server import ContainerExecServer
from adgn.mcp.notifications.buffer import NotificationsBuffer
from adgn.mcp.stubs.typed_stubs import TypedClient
from adgn.mcp.testing.simple_servers import make_simple_mcp as _make_simple_mcp
from adgn.props.db.models import CanonicalIssuesSnapshot
from tests.support.responses import _StepRunner
from tests.support.steps import Step
from tests.support.types import McpServerSpecs

# Empty canonical issues snapshot for GraderRun fixtures.
# Format matches GraderRun.canonical_issues_snapshot Pydantic model.
EMPTY_CANONICAL_ISSUES_SNAPSHOT = CanonicalIssuesSnapshot(true_positives=[], false_positives=[])

# Test server mount name used in fixtures
TEST_BACKEND_SERVER_NAME = "backend"


@pytest.fixture
def mock_registry(sqlite_persistence):
    """Create mock infrastructure registry using real persistence.

    Used by mcp_bridge and mcp/agents tests. Mocks agent container tracking
    while using real persistence for data storage.
    """
    registry = MagicMock()
    registry.persistence = sqlite_persistence
    registry.list_agents.return_value = []
    registry.is_external.return_value = False
    return registry


@pytest.fixture
def test_agent_id(request: pytest.FixtureRequest) -> str:
    """Generate a sanitized agent ID from the test node ID."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", request.node.nodeid) or "tests"


@pytest.fixture
async def compositor():
    """Fresh Compositor instance for each test with automatic lifecycle management.

    The compositor is entered as a context manager automatically, so tests can
    mount servers and use it immediately without explicit 'async with'.
    """
    async with Compositor() as comp:
        yield comp


@pytest.fixture
async def compositor_client(compositor):
    """Client connected to the compositor."""
    async with Client(compositor) as client:
        yield client


@pytest.fixture
async def test_policy_engine(sqlite_persistence, async_docker_client):
    """Policy engine fixture with approve-all policy for testing."""
    return await _create_test_policy_engine(sqlite_persistence, async_docker_client)


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

    # Register custom markers
    config.addinivalue_line(
        "markers",
        "requires_network_isolation: mark test as requiring container network isolation "
        "(skipped in Claude Code Web where only host networking works)",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        if item.get_closest_marker("requires_sandbox_exec") is not None:
            item.add_marker(pytest.mark.macos)


def pytest_runtest_setup(item: pytest.Item) -> None:
    if item.get_closest_marker("requires_sandbox_exec") is not None and platform.system() != "Darwin":
        pytest.skip("seatbelt sandbox tests require macOS (sandbox-exec unavailable)")
    if item.get_closest_marker("macos") is not None and platform.system() != "Darwin":
        pytest.skip("macOS-only test")

    # Skip network isolation tests in Claude Code Web (microVM doesn't support network namespaces)
    if item.get_closest_marker("requires_network_isolation") is not None:
        env = get_claude_code_web_env()
        if not env.supports_container_network_isolation:
            pytest.skip(
                "Test requires container network isolation which is not supported in Claude Code Web. "
                "Use host networking or run locally."
            )

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
async def async_docker_client():
    """Provide an async Docker client for FastMCP container servers.

    Creates an aiodocker.Docker() instance for tests that need Docker operations.
    Function-scoped due to pytest-asyncio event loop lifecycle requirements.

    This is separate from docker_client which provides sync docker.DockerClient.
    Use this for async contexts (FastMCP servers), use docker_client for sync operations.
    """
    client = aiodocker.Docker()
    try:
        yield client
    finally:
        await client.close()


@pytest.fixture
async def sqlite_persistence(tmp_path):
    """Create isolated SQLite persistence in per-test tmpdir.

    Each test gets its own tmp_path directory, so the database name can be constant.
    This ensures proper isolation when running tests in parallel with pytest-xdist.

    Args:
        tmp_path: Per-test temporary directory (from pytest)
    """
    p = SQLitePersistence(tmp_path / "agent.sqlite")
    await p.ensure_schema()
    return p


@pytest.fixture
async def make_approval_policy_server(
    sqlite_persistence, test_agent_id, async_docker_client
) -> Callable[[str], Awaitable[PolicyEngine]]:
    """Factory producing PolicyEngine instances with per-test defaults.

    The returned engine owns .reader, .proposer and .approver sub-servers.
    """

    async def _make(policy_source: str) -> PolicyEngine:
        # Create agent in DB first to satisfy FK constraints
        agent_id_resolved = await sqlite_persistence.create_agent(
            mcp_config=MCPConfig(), metadata=AgentMetadata(preset="test")
        )
        return PolicyEngine(
            agent_id=agent_id_resolved,
            persistence=sqlite_persistence,
            policy_source=policy_source,
            docker_client=async_docker_client,
        )

    return _make


@pytest.fixture
async def approval_policy_server(sqlite_persistence, async_docker_client) -> PolicyEngine:
    """PolicyEngine fixture that owns .reader, .proposer and .approver sub-servers."""
    return PolicyEngine(
        agent_id="tests",
        persistence=sqlite_persistence,
        policy_source=load_default_policy_source(),
        docker_client=async_docker_client,
    )


@pytest.fixture
def policy_allow_all() -> str:
    """Return the text of the approve-all policy from packaged resources."""
    return approve_all_policy_text()


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
def make_simple_mcp() -> FlatModelMixin:
    """Lightweight FastMCP backend with simple tools for tests."""
    return _make_simple_mcp()


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


async def _create_test_policy_engine(sqlite_persistence, async_docker_client) -> PolicyEngine:
    """Create a test policy engine with approve-all policy.

    Helper to avoid duplication in make_policy_gateway_client and make_policy_gateway_compositor.
    """
    agent_id_resolved = await sqlite_persistence.create_agent(
        mcp_config=MCPConfig(), metadata=AgentMetadata(preset="test")
    )
    return PolicyEngine(
        agent_id=agent_id_resolved,
        persistence=sqlite_persistence,
        policy_source=approve_all_policy_text(),
        docker_client=async_docker_client,
    )


@pytest.fixture
def _setup_policy_gateway_compositor(sqlite_persistence, async_docker_client, test_agent_id):
    """Fixture factory for AgentContainerCompositor with policy gateway middleware.

    Returns a factory function that accepts servers and optional policy_engine.
    Common fixtures (sqlite_persistence, etc.) are injected via pytest.

    Usage (via make_policy_gateway_client or make_policy_gateway_compositor):
        async with make_policy_gateway_client(servers) as client: ...
        async with make_policy_gateway_compositor(servers) as comp: ...
    """

    @asynccontextmanager
    async def _factory(servers: McpServerSpecs, *, policy_engine: PolicyEngine | None = None):
        if policy_engine is None:
            policy_engine = await _create_test_policy_engine(sqlite_persistence, async_docker_client)

        comp = AgentContainerCompositor(
            approval_engine=policy_engine,
            ui_bus=None,  # Tests don't need UI by default
            async_docker_client=async_docker_client,
            persistence=sqlite_persistence,
            agent_id=test_agent_id,
        )
        async with comp:
            # Install policy gateway middleware (required for policy enforcement)
            comp.add_middleware(policy_engine.gateway)
            await _mount_servers(comp, servers)
            yield comp

    return _factory


@pytest.fixture
def make_policy_gateway_client(_setup_policy_gateway_compositor):
    """Async helper to open an AgentContainerCompositor with policy gateway, yielding just the client.

    Usage:
        async with make_policy_gateway_client(servers) as client:
            result = await client.call_tool(...)

    For tests that need access to the compositor or engine, use make_policy_gateway_compositor instead.

    TODO: Deduplicate this setup with production (AgentContainer._setup_mcp_infrastructure).
    """

    @asynccontextmanager
    async def _open(servers: McpServerSpecs, *, policy_engine: PolicyEngine | None = None):
        async with _setup_policy_gateway_compositor(servers, policy_engine=policy_engine) as comp, Client(comp) as sess:
            yield sess

    return _open


@pytest.fixture
def make_policy_gateway_compositor(_setup_policy_gateway_compositor):
    """Async helper factory yielding typed AgentContainerCompositor.

    Usage:
        async with make_policy_gateway_compositor(servers) as comp:
            # comp is the typed AgentContainerCompositor instance
            # Access policy engine via comp._approval_engine
            # Create client with: async with Client(comp) as sess: ...
            ...

    For tests that only need the client, prefer make_policy_gateway_client instead.

    TODO: Deduplicate this setup with production (AgentContainer._setup_mcp_infrastructure).
    """

    @asynccontextmanager
    async def _open(servers: McpServerSpecs, *, policy_engine: PolicyEngine | None = None):
        async with _setup_policy_gateway_compositor(servers, policy_engine=policy_engine) as comp:
            yield comp

    return _open


# Note: legacy open_mcp_with_slots fixture has been removed. Use make_policy_gateway_client or make_policy_gateway_compositor instead.


@pytest.fixture
async def policy_gateway_client(make_policy_gateway_client, make_simple_mcp):
    """Ready-to-use client with make_simple_mcp mounted and allow-all policy.

    For tests that just need a simple compositor with a backend server.
    """
    async with make_policy_gateway_client({TEST_BACKEND_SERVER_NAME: make_simple_mcp}) as sess:
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
        async with Compositor() as comp:
            await _mount_servers(comp, servers)
            async with Client(comp) as sess:
                yield sess, comp

    return _open


# Removed: _extract_policy_gateway_client helper (no longer needed with simpler fixture structure)


@pytest.fixture
async def policy_gateway_compositor_box(make_policy_gateway_compositor, async_docker_client):
    """Async fixture with box Docker exec server and policy gateway.

    Mounts a per-session container exec server under name "box" with policy gateway.
    Yields AgentContainerCompositor.
    """
    server = ContainerExecServer(async_docker_client, make_container_opts("python:3.12-slim"))
    async with make_policy_gateway_compositor({"box": server}) as comp:
        yield comp


@pytest.fixture
async def policy_gateway_client_box(policy_gateway_compositor_box):
    """MCP client for box Docker exec server."""
    async with Client(policy_gateway_compositor_box) as sess:
        yield sess


@pytest.fixture
async def policy_gateway_compositor_echo(echo_spec, make_policy_gateway_compositor):
    """Async fixture with echo server and policy gateway.

    Yields AgentContainerCompositor.
    """
    async with make_policy_gateway_compositor(echo_spec) as comp:
        yield comp


@pytest.fixture
async def policy_gateway_client_echo(policy_gateway_compositor_echo):
    """MCP client for echo server."""
    async with Client(policy_gateway_compositor_echo) as sess:
        yield sess


@pytest.fixture
async def mcp_client_echo(make_compositor, echo_spec):
    """Plain MCP client with echo server (no policy gateway).

    For tests that don't need policy approval but need a simple MCP server.
    Using plain Compositor avoids Docker overhead and potential timeouts.
    """
    async with make_compositor(echo_spec) as (client, _comp):
        yield client


@pytest.fixture
async def mcp_client_box(docker_exec_server_py312slim, compositor, compositor_client):
    """MCP client with box Docker exec server (no policy gateway).

    For tests that need Docker exec but don't need policy approval.
    Uses the standard docker_exec_server_py312slim fixture and mounts it as 'box'.
    """
    await compositor.mount_inproc("box", docker_exec_server_py312slim)
    return compositor_client


@pytest.fixture
def make_buffered_client():
    """Async helper to open a Compositor + Client with NotificationsBuffer.

    Yields (client, compositor, buffer) so tests can read buffered notifications
    or pass buffer.poll into handlers.
    """

    @asynccontextmanager
    async def _open(servers: McpServerSpecs):
        # Pass explicit version to avoid importlib.metadata.version() lookup which can hang under pytest-xdist
        async with Compositor(version="1.0.0-test") as comp:
            await _mount_servers(comp, servers)
            buf = NotificationsBuffer(compositor=comp)
            async with Client(comp, message_handler=buf.handler) as sess:
                yield sess, comp, buf

    return _open


@pytest.fixture
async def docker_exec_server_py312slim(async_docker_client):
    """Canonical Docker exec server using python:3.12-slim image."""
    opts = make_container_opts("python:3.12-slim")
    return ContainerExecServer(async_docker_client, opts)


@pytest.fixture
async def typed_docker_client(make_typed_mcp, docker_exec_server_py312slim):
    """Typed MCP client for docker exec server with python:3.12-slim.

    Yields (TypedClient, session) tuple for direct use in tests.
    """
    async with make_typed_mcp(docker_exec_server_py312slim, "docker") as (client, session):
        yield client, session


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
async def make_decision_engine(
    make_approval_policy_server: Callable[[str], Awaitable[PolicyEngine]],
) -> Callable[[ApprovalDecision], Awaitable[PolicyEngine]]:
    """Factory for creating PolicyEngine with a specific decision policy.

    Usage:
        engine = await make_decision_engine(ApprovalDecision.ALLOW)
        engine = await make_decision_engine(ApprovalDecision.DENY_ABORT)
        engine = await make_decision_engine(ApprovalDecision.ASK)

    Thin wrapper around make_approval_policy_server that handles policy source generation.
    """

    async def _make(decision: ApprovalDecision) -> PolicyEngine:
        policy_source = make_policy_source(decision)
        return await make_approval_policy_server(policy_source)

    return _make


@pytest.fixture
async def approval_policy_reader_allow_all(sqlite_persistence, async_docker_client) -> FastMCP:
    """Approval policy reader server with an approve-all policy program.

    Uses the packaged approve_all.py source and evaluates via Docker.
    """
    engine = PolicyEngine(
        agent_id="tests",
        persistence=sqlite_persistence,
        policy_source=approve_all_policy_text(),
        docker_client=async_docker_client,
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


def make_container_opts(
    image: str,
    *,
    working_dir: Path = Path("/workspace"),
    ephemeral: bool = True,
    network_mode: str | None = None,
) -> ContainerOptions:
    """Create standard ContainerOptions with proper Path type conversion.

    Args:
        image: Docker image to use
        working_dir: Working directory inside container
        ephemeral: Whether container should be removed after use
        network_mode: Network mode for the container. If None, uses environment-aware
            default (host mode in Claude Code Web, none otherwise).

    Returns:
        ContainerOptions configured for the current environment
    """
    # Use environment-aware network mode if not explicitly specified
    resolved_network_mode = network_mode if network_mode is not None else get_test_network_mode("none")
    return ContainerOptions(
        image=image,
        working_dir=working_dir,
        binds=None,
        ephemeral=ephemeral,
        network_mode=resolved_network_mode,
    )


# --- Shared lightweight fixtures used across agent and MCP tests ---


@pytest.fixture
def echo_spec(make_simple_mcp) -> McpServerSpecs:
    """In-proc FastMCP server spec for echo tests."""
    return {"echo": make_simple_mcp}


# --- Helpers for constructing MCP tool inputs ---
# (make_exec_input moved to adgn.mcp.exec.models for production use)
