from __future__ import annotations

from contextlib import asynccontextmanager
import sys

from fastmcp.client import Client
from fastmcp.mcp_config import StdioMCPServer
import pytest

from adgn.agent.policies.policy_types import ApprovalDecision
from adgn.mcp.approval_policy.server import ApprovalPolicyServer
from adgn.mcp.compositor.clients import CompositorAdminClient
from adgn.mcp.compositor.setup import mount_standard_inproc_servers
from adgn.mcp.resources.clients import ResourcesClient
from adgn.mcp.resources.server import make_resources_server


@pytest.fixture
def stdio_echo_spec() -> StdioMCPServer:
    """Launch packaged echo server module via -m as a stdio spec."""
    return StdioMCPServer(command=sys.executable, args=["-m", "adgn.mcp.testing.stdio_app"])


@pytest.fixture
async def admin_client(compositor):
    """Admin client with standard admin/meta servers mounted on compositor.

    Tests needing direct compositor access can request it as a separate fixture.
    """
    await mount_standard_inproc_servers(compositor=compositor, gateway_client=None)
    async with Client(compositor) as client:
        yield CompositorAdminClient(client)


@pytest.fixture
async def resources_client(compositor):
    """Resources client mounted using a real gateway client.

    Yields ResourcesClient for tests that need to subscribe/unsubscribe and read the index.
    Tests needing direct compositor access can request it as a separate fixture.
    """
    async with Client(compositor) as gw:
        res_server = make_resources_server(gateway_client=gw, compositor=compositor)
        async with Client(res_server) as res_client:
            yield ResourcesClient(res_client)


def _policy_source_for_decision(decision: ApprovalDecision) -> str:
    """Minimal policy program that returns a fixed decision."""
    d = str(decision.value)
    return (
        f"import sys, json\n_ = json.load(sys.stdin)\nprint(json.dumps({{'decision': '{d}', 'rationale': 'test'}}))\n"
    )


@pytest.fixture
def make_pg_session_with_decision(make_policy_engine, make_pg_session, backend_server):
    """Factory to open a pg_session with a policy that returns a fixed decision.

    Usage:
        async with make_pg_session_with_decision(ApprovalDecision.ALLOW) as sess:
            ...
    """

    @asynccontextmanager
    async def _open(decision: ApprovalDecision, *, notifier=None):
        eng = make_policy_engine(_policy_source_for_decision(decision))
        reader = ApprovalPolicyServer(eng)
        async with make_pg_session({"backend": backend_server, "approval_policy": reader}, notifier=notifier) as sess:
            yield sess

    return _open
