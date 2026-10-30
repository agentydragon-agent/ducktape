"""Executable mcp scenarios sharing one k3s stack."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
import pytest_bazel

# gazelle:include_dep @pypi//protobuf
from agentplane.app.testing.client import Client
from agentplane.proto import runner_pb2
from agentplane.system_tests.conftest import Sandboxes
from agentplane.system_tests.k3s.stack import Stack
from agentplane.system_tests.operator_login import (
    LoginBlockedError,
    OperatorCredentials,
    app_origin,
    login_operator,
    read_operator_credentials,
    verify_action_federation,
)
from agentplane.system_tests.scenarios import dcr, mcp
from agentplane.system_tests.scripted_upstream import ScriptedUpstream


@pytest.fixture
def policy_objects(deployment: Stack) -> Iterator[mcp.PolicyObjects]:
    objects = mcp.PolicyObjects(namespace=deployment.namespace)
    try:
        yield objects
    finally:
        objects.delete_all()


@pytest.fixture
def operator_credentials(pytestconfig: pytest.Config, deployment: Stack) -> OperatorCredentials:
    if deployment.mcp_fixtures is None:
        raise ValueError("operator login requires MCP fixtures in this deployment")
    if pytestconfig.option.showlocals:
        pytest.fail("BLOCKED: disable pytest local-variable dumps before reading operator credentials", pytrace=False)
    try:
        return read_operator_credentials()
    except LoginBlockedError as exc:
        pytest.fail(str(exc), pytrace=False)


@pytest.fixture
async def operator_bff(base_url: str, operator_credentials: OperatorCredentials) -> AsyncIterator[httpx.AsyncClient]:
    """A real app-issued session. No credential injection, fabricated cookies, or DB writes."""
    # HTTP debug logging includes cookie/token headers and callback query strings. Suppress it
    # throughout this client lifetime (including failed assertions/teardown), even under --log-cli-level.
    previous_logging = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        origin = str(app_origin(base_url)).rstrip("/")
        async with httpx.AsyncClient(base_url=origin, timeout=30, follow_redirects=False) as http:
            try:
                await login_operator(http, operator_credentials)
            except LoginBlockedError as exc:
                pytest.fail(str(exc), pytrace=False)
            except httpx.HTTPError, httpx.InvalidURL, ValueError, KeyError, TypeError:
                pytest.fail("BLOCKED: OIDC transport or response invalid; auth details withheld", pytrace=False)
            http.headers["Origin"] = origin
            await verify_action_federation(http)
            yield http
    except LoginBlockedError as exc:
        pytest.fail(str(exc), pytrace=False)
    finally:
        logging.disable(previous_logging)


async def test_deployed_discovery_and_registration(pytestconfig: pytest.Config) -> None:
    await dcr.deployed_discovery_and_registration(pytestconfig)


@pytest.mark.scripted_model
async def test_agent_executes_mcp_action(
    client: Client,
    sandbox: Sandboxes,
    harness: runner_pb2.Harness,
    offered_model: str,
    scripted: ScriptedUpstream,
    policy_objects: mcp.PolicyObjects,
) -> None:
    await mcp.agent_executes_mcp_action(client, sandbox, harness, offered_model, scripted, policy_objects)


@pytest.mark.scripted_model
async def test_agent_mcp_bff_decision(
    operator_bff: httpx.AsyncClient,
    operator_credentials: OperatorCredentials,
    client: Client,
    sandbox: Sandboxes,
    harness: runner_pb2.Harness,
    offered_model: str,
    scripted: ScriptedUpstream,
) -> None:
    await mcp.agent_mcp_bff_decision(
        operator_bff, operator_credentials, client, sandbox, harness, offered_model, scripted
    )


@pytest.mark.scripted_model
async def test_launcher_drives_only_the_sandbox_it_launched(
    operator_bff: httpx.AsyncClient,
    client: Client,
    sandbox: Sandboxes,
    harness: runner_pb2.Harness,
    offered_model: str,
    scripted: ScriptedUpstream,
    policy_objects: mcp.PolicyObjects,
) -> None:
    await mcp.launcher_drives_only_the_sandbox_it_launched(
        operator_bff, client, sandbox, harness, offered_model, scripted, policy_objects
    )


@pytest.mark.scripted_model
async def test_operator_links_oauth_mcp_server(
    operator_bff: httpx.AsyncClient,
    operator_credentials: OperatorCredentials,
    client: Client,
    sandbox: Sandboxes,
    harness: runner_pb2.Harness,
    offered_model: str,
    scripted: ScriptedUpstream,
    policy_objects: mcp.PolicyObjects,
) -> None:
    await mcp.operator_links_oauth_mcp_server(
        operator_bff, operator_credentials, client, sandbox, harness, offered_model, scripted, policy_objects
    )


@pytest.mark.scripted_model
async def test_policy_binding_auto_approves_the_bound_sandbox(
    operator_bff: httpx.AsyncClient,
    client: Client,
    sandbox: Sandboxes,
    harness: runner_pb2.Harness,
    offered_model: str,
    scripted: ScriptedUpstream,
    policy_objects: mcp.PolicyObjects,
) -> None:
    await mcp.policy_binding_auto_approves_the_bound_sandbox(
        operator_bff, client, sandbox, harness, offered_model, scripted, policy_objects
    )


if __name__ == "__main__":
    pytest_bazel.main()
