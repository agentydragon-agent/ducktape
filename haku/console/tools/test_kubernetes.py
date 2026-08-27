from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
import pytest_bazel
from fastmcp import Client
from pydantic import ValidationError

from haku.console.grant_principal import (
    AgentGrantPrincipal,
    GrantPrincipalKind,
    RequestPrincipal,
    SessionGrantPrincipal,
)
from haku.console.kubernetes_authorization import (
    AuthorizationResponse,
    KubernetesAuthorizationSource,
    RequestAttributes,
)
from haku.console.kubernetes_grant_models import (
    KubernetesGrant,
    KubernetesGrantScopeKind,
    KubernetesGrantSpec,
    KubernetesGrantStatus,
    KubernetesNamespacesGrantScope,
    KubernetesRule,
)
from haku.console.mcp_execution import AgentMcpExecutionCaller, McpExecutionContext, OperatorMcpExecutionCaller
from haku.console.tools.kubernetes import KubernetesAccessCheck, KubernetesToolsService, build_mcp

_AGENT = UUID("10000000-0000-4000-8000-000000000001")
_GRANT = UUID("20000000-0000-4000-8000-000000000002")
_SESSION = UUID("40000000-0000-4000-8000-000000000004")
_NOW = datetime(2026, 8, 20, tzinfo=UTC)
_SCOPE = KubernetesNamespacesGrantScope(namespaces=("demo",))
_RULE = KubernetesRule(api_groups=("",), resources=("pods",), verbs=("get",))
_REQUEST = RequestAttributes(
    resource_request=True,
    verb="get",
    api_version="v1",
    namespace="demo",
    resource="pods",
    path="/api/v1/namespaces/demo/pods",
)
# The complete trusted identity `_agent_context()` carries, as the grant reads must forward it.
_REQUEST_PRINCIPAL = RequestPrincipal(agent_id=_AGENT, session_id=_SESSION, access_profile_id="public-coder")


def _agent_context(*, session_id: UUID | None = _SESSION) -> McpExecutionContext:
    return McpExecutionContext(
        caller=AgentMcpExecutionCaller(
            principal=RequestPrincipal(agent_id=_AGENT, session_id=session_id, access_profile_id="public-coder")
        ),
        tool_call_id="tc_create_grant",
        approving_operator_id=None,
        approval_policy_id=None,
    )


def _operator_context() -> McpExecutionContext:
    return McpExecutionContext(
        caller=OperatorMcpExecutionCaller(operator_id=UUID(int=9)),
        tool_call_id="tc_operator",
        approving_operator_id=None,
        approval_policy_id=None,
    )


@pytest.fixture
def grant() -> KubernetesGrant:
    return KubernetesGrant(
        grant_id=_GRANT,
        owner_agent_id=_AGENT,
        principal=AgentGrantPrincipal(agent_id=_AGENT),
        source_tool_call_id="tc_create_grant",
        scope=_SCOPE,
        rules=(_RULE,),
        status=KubernetesGrantStatus.ACTIVE,
        created_at=_NOW,
        expires_at=datetime(2026, 8, 20, 1, tzinfo=UTC),
    )


@pytest.fixture
def grants(grant: KubernetesGrant) -> AsyncMock:
    mock = AsyncMock()
    mock.create_grants.return_value = (grant,)
    mock.list_applicable_grants.return_value = (grant,)
    mock.get_applicable_grant.return_value = grant
    mock.release_applicable_grants.return_value = (grant,)
    return mock


@pytest.fixture
def authorization() -> AsyncMock:
    mock = AsyncMock()
    mock.authorize_agent.return_value = AuthorizationResponse(
        allowed=True, reason="standing", source=KubernetesAuthorizationSource.SAR, decision_id="sar:decision"
    )
    return mock


@pytest.fixture
def service(grants: AsyncMock, authorization: AsyncMock) -> KubernetesToolsService:
    return KubernetesToolsService(grants=grants, authorization=authorization)


async def test_server_exposes_exact_stable_tool_set_without_context_argument(service: KubernetesToolsService) -> None:
    async with Client(build_mcp(service)) as client:
        tools = await client.list_tools()
    assert {tool.name for tool in tools} == {"can_i", "create_grant", "list_grants", "get_grant", "release_grants"}
    for tool in tools:
        assert "context" not in tool.inputSchema.get("properties", {})
    create_grant = next(tool for tool in tools if tool.name == "create_grant")
    assert set(create_grant.inputSchema["properties"]) == {"grants", "duration_seconds", "applies_to"}
    assert create_grant.inputSchema["properties"]["applies_to"]["default"] == "agent"
    assert create_grant.inputSchema["properties"]["grants"]["minItems"] == 1
    assert create_grant.inputSchema["properties"]["grants"]["maxItems"] == 32
    release_grants = next(tool for tool in tools if tool.name == "release_grants")
    assert set(release_grants.inputSchema["properties"]) == {"grant_ids", "reason"}
    assert release_grants.inputSchema["properties"]["grant_ids"]["minItems"] == 1
    assert release_grants.inputSchema["properties"]["grant_ids"]["maxItems"] == 32


async def test_create_uses_trusted_agent_current_tool_call_and_exact_grants(
    service: KubernetesToolsService, grants: AsyncMock
) -> None:
    requested = [
        KubernetesGrantSpec(scope=_SCOPE, rules=(_RULE,)),
        KubernetesGrantSpec(
            scope=KubernetesNamespacesGrantScope(namespaces=("other",)),
            rules=(KubernetesRule(api_groups=("apps",), resources=("deployments",), verbs=("patch",)),),
        ),
    ]
    await service.create_grants(context=_agent_context(), grants=requested, duration_seconds=60)
    kwargs = grants.create_grants.await_args.kwargs
    assert kwargs["owner_agent_id"] == _AGENT
    assert kwargs["grant_principal"] == AgentGrantPrincipal(agent_id=_AGENT)
    assert kwargs["source_tool_call_id"] == "tc_create_grant"
    assert kwargs["grants"] == requested


@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(
            lambda service: service.create_grants(
                context=_operator_context(),
                grants=[KubernetesGrantSpec(scope=_SCOPE, rules=(_RULE,))],
                duration_seconds=60,
            ),
            id="create",
        ),
        pytest.param(lambda service: service.list_grants(context=_operator_context()), id="list"),
        pytest.param(lambda service: service.get_grant(context=_operator_context(), grant_id=_GRANT), id="get"),
        pytest.param(
            lambda service: service.release_grants(context=_operator_context(), grant_ids=[_GRANT]), id="release"
        ),
    ],
)
async def test_operator_cannot_mint_or_inspect_agent_grants(
    service: KubernetesToolsService, operation: Callable[[KubernetesToolsService], Awaitable[object]]
) -> None:
    with pytest.raises(PermissionError):
        await operation(service)


async def test_inspection_uses_the_complete_trusted_request_principal(
    service: KubernetesToolsService, grants: AsyncMock, grant: KubernetesGrant
) -> None:
    assert await service.list_grants(context=_agent_context()) == (grant,)
    assert await service.get_grant(context=_agent_context(), grant_id=_GRANT) == grant

    grants.list_applicable_grants.assert_awaited_once_with(request_principal=_REQUEST_PRINCIPAL)
    grants.get_applicable_grant.assert_awaited_once_with(request_principal=_REQUEST_PRINCIPAL, grant_id=_GRANT)


async def test_release_uses_trusted_agent_and_supplied_grant_order(
    service: KubernetesToolsService, grants: AsyncMock, grant: KubernetesGrant
) -> None:
    other = UUID("20000000-0000-4000-8000-000000000003")
    grants.release_applicable_grants.return_value = (grant, grant.model_copy(update={"grant_id": other}))

    result = await service.release_grants(context=_agent_context(), grant_ids=[_GRANT, other], reason="probe complete")

    assert [item.grant_id for item in result] == [_GRANT, other]
    grants.release_applicable_grants.assert_awaited_once_with(
        request_principal=_REQUEST_PRINCIPAL, grant_ids=[_GRANT, other], reason="probe complete"
    )


async def test_can_i_uses_shared_agent_evaluator_and_returns_source(
    service: KubernetesToolsService, authorization: AsyncMock
) -> None:
    result = await service.can_i(context=_agent_context(), requests=[KubernetesAccessCheck(attributes=_REQUEST)])
    assert result[0].allowed is True
    assert result[0].source is KubernetesAuthorizationSource.SAR
    kwargs = authorization.authorize_agent.await_args.kwargs
    assert kwargs["request_principal"] == _REQUEST_PRINCIPAL
    request = kwargs["request"]
    assert request.attributes == _REQUEST
    assert request.required_scope == _SCOPE
    assert request.required_rules == [_RULE]


async def test_create_session_scope_uses_exact_trusted_agent_and_session(
    service: KubernetesToolsService, grants: AsyncMock
) -> None:
    await service.create_grants(
        context=_agent_context(),
        grants=[KubernetesGrantSpec(scope=_SCOPE, rules=(_RULE,))],
        duration_seconds=60,
        applies_to=GrantPrincipalKind.SESSION,
    )
    assert grants.create_grants.await_args.kwargs["grant_principal"] == SessionGrantPrincipal(session_id=_SESSION)


async def test_create_session_scope_rejects_static_agent_context(
    service: KubernetesToolsService, grants: AsyncMock
) -> None:
    with pytest.raises(PermissionError, match="live session-authenticated"):
        await service.create_grants(
            context=_agent_context(session_id=None),
            grants=[KubernetesGrantSpec(scope=_SCOPE, rules=(_RULE,))],
            duration_seconds=60,
            applies_to=GrantPrincipalKind.SESSION,
        )
    grants.create_grants.assert_not_awaited()


def test_can_i_requires_explicit_scope_for_unnamespaced_resource_request() -> None:
    attributes = RequestAttributes(
        resource_request=True, verb="list", api_version="v1", resource="pods", path="/api/v1/pods"
    )
    with pytest.raises(ValidationError, match="all_namespaces or cluster"):
        KubernetesAccessCheck(attributes=attributes)
    check = KubernetesAccessCheck(
        attributes=attributes, unnamespaced_resource_kind=KubernetesGrantScopeKind.ALL_NAMESPACES
    )
    assert check.unnamespaced_resource_kind is KubernetesGrantScopeKind.ALL_NAMESPACES


if __name__ == "__main__":
    pytest_bazel.main()
