"""PostgreSQL lifecycle and provenance tests for temporary Kubernetes grants."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
import pytest_bazel
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from haku.console.agents.authorization import fingerprint_static_token
from haku.console.database_schema import (
    Agent,
    CredentialBinding,
    KubernetesGrantRow,
    McpToolCall,
    McpToolCallPrincipal,
    StaticCredential,
)
from haku.console.kubernetes_grant_models import (
    KubernetesAllNamespacesGrantScope,
    KubernetesClusterGrantScope,
    KubernetesGrantNotFoundError,
    KubernetesGrantSourceError,
    KubernetesGrantSpec,
    KubernetesGrantStatus,
    KubernetesNamespacesGrantScope,
    KubernetesNonResourceGrantScope,
    KubernetesRule,
)
from haku.console.kubernetes_grant_repository import PostgresKubernetesGrantRepository
from haku.console.tool_calls import ToolCallStatus

_NOW = datetime(2026, 8, 20, 0, 0, tzinfo=UTC)
_RULE = KubernetesRule(api_groups=("",), resources=("pods",), verbs=("get",))
_SCOPE = KubernetesNamespacesGrantScope(namespaces=("diagnostics", "public-coder-agent"))
_CLUSTER_RULE = KubernetesRule(api_groups=("",), resources=("nodes",), verbs=("get",))
_NON_RESOURCE_RULE = KubernetesRule(non_resource_urls=("/version",), verbs=("get",))
_RAW_GRANT_INSERT = text(
    """
    INSERT INTO kubernetes_grants (
        grant_id, agent_id, source_tool_call_id, scope, rules, status,
        created_at, expires_at, ended_at, end_reason
    ) VALUES (
        :grant_id, :agent_id, :source_tool_call_id, CAST(:scope AS jsonb),
        CAST(:rules AS jsonb), 'active', :created_at, :expires_at, NULL, NULL
    )
    """
)


async def _default_agent(sessions: async_sessionmaker[AsyncSession]) -> tuple[UUID, UUID]:
    async with sessions() as session:
        result = await session.execute(
            select(CredentialBinding.agent_id, CredentialBinding.binding_id)
            .join(StaticCredential, StaticCredential.binding_id == CredentialBinding.binding_id)
            .join(Agent, Agent.agent_id == CredentialBinding.agent_id)
            .where(StaticCredential.credential_fingerprint == fingerprint_static_token("default-agent-token"))
        )
        return cast(tuple[UUID, UUID], result.one())


async def _source_call(
    sessions: async_sessionmaker[AsyncSession],
    *,
    binding_id: UUID,
    server_id: str = "kubernetes",
    tool_name: str = "create_grant",
    approval_policy_id: str | None = None,
) -> str:
    tool_call_id = f"tc_{uuid4().hex}"
    async with sessions.begin() as session:
        session.add(
            McpToolCall(
                tool_call_id=tool_call_id,
                server_id=server_id,
                tool_name=tool_name,
                status=ToolCallStatus.RUNNING,
                created_at=_NOW,
                updated_at=_NOW,
                arguments_json={"duration_seconds": 300},
                rationale="temporary diagnostic access",
                title="Kubernetes diagnostic grant",
                result_json=None,
                error=None,
                denial_reason=None,
                withdrawal_reason=None,
                approval_policy_id=approval_policy_id,
                auto_approval_evaluation=None,
                approved_at=_NOW,
            )
        )
        session.add(McpToolCallPrincipal(tool_call_id=tool_call_id, operator_id=None, binding_id=binding_id))
    return tool_call_id


async def _insert_raw_grant(
    sessions: async_sessionmaker[AsyncSession],
    *,
    agent_id: UUID,
    source_tool_call_id: str,
    scope: dict[str, object],
    rule: KubernetesRule,
) -> None:
    async with sessions.begin() as session:
        await session.execute(
            _RAW_GRANT_INSERT,
            {
                "grant_id": uuid4(),
                "agent_id": agent_id,
                "source_tool_call_id": source_tool_call_id,
                "scope": json.dumps(scope),
                "rules": json.dumps([rule.model_dump(mode="json")]),
                "created_at": _NOW,
                "expires_at": _NOW + timedelta(minutes=5),
            },
        )


def test_repository_enforces_source_provenance_and_lifecycle(make_client: Any) -> None:
    with make_client() as client:
        app = cast(FastAPI, client.app)
        sessions = cast(async_sessionmaker[AsyncSession], app.state.db_sessions)
        assert client.portal is not None
        agent_id, binding_id = client.portal.call(_default_agent, sessions)
        source_tool_call_id = client.portal.call(partial(_source_call, sessions, binding_id=binding_id))
        repository = PostgresKubernetesGrantRepository(sessions)

        async def exercise() -> None:
            grant = await repository.create(
                agent_id=agent_id,
                source_tool_call_id=source_tool_call_id,
                scope=_SCOPE,
                rules=(_RULE,),
                created_at=_NOW,
                expires_at=_NOW + timedelta(minutes=5),
            )
            assert grant.status is KubernetesGrantStatus.ACTIVE
            assert (await repository.get(agent_id=agent_id, grant_id=grant.grant_id)) == grant
            assert await repository.active_for_agent(agent_id=agent_id, now=_NOW) == (grant,)

            released = await repository.release(
                agent_id=agent_id,
                grant_id=grant.grant_id,
                reason="no longer needed",
                ended_at=_NOW + timedelta(minutes=1),
            )
            assert released.status is KubernetesGrantStatus.RELEASED
            assert await repository.active_for_agent(agent_id=agent_id, now=_NOW) == ()

        client.portal.call(exercise)


def test_repository_atomically_creates_multiple_grants_from_one_source(make_client: Any) -> None:
    with make_client() as client:
        app = cast(FastAPI, client.app)
        sessions = cast(async_sessionmaker[AsyncSession], app.state.db_sessions)
        assert client.portal is not None
        agent_id, binding_id = client.portal.call(_default_agent, sessions)
        source_tool_call_id = client.portal.call(partial(_source_call, sessions, binding_id=binding_id))
        repository = PostgresKubernetesGrantRepository(sessions)

        async def exercise() -> None:
            grants = await repository.create_many(
                agent_id=agent_id,
                source_tool_call_id=source_tool_call_id,
                grants=(
                    KubernetesGrantSpec(scope=_SCOPE, rules=(_RULE,)),
                    KubernetesGrantSpec(scope=KubernetesClusterGrantScope(), rules=(_CLUSTER_RULE,)),
                ),
                created_at=_NOW,
                expires_at=_NOW + timedelta(minutes=5),
            )
            assert len(grants) == 2
            assert len({grant.grant_id for grant in grants}) == 2
            assert {grant.source_tool_call_id for grant in grants} == {source_tool_call_id}
            assert {grant.created_at for grant in grants} == {_NOW}
            assert {grant.expires_at for grant in grants} == {_NOW + timedelta(minutes=5)}

            retried = await repository.create_many(
                agent_id=agent_id,
                source_tool_call_id=source_tool_call_id,
                grants=(
                    KubernetesGrantSpec(scope=_SCOPE, rules=(_RULE,)),
                    KubernetesGrantSpec(scope=KubernetesClusterGrantScope(), rules=(_CLUSTER_RULE,)),
                ),
                created_at=_NOW + timedelta(seconds=10),
                expires_at=_NOW + timedelta(minutes=10),
            )
            assert tuple(grant.grant_id for grant in retried) == tuple(grant.grant_id for grant in grants)
            assert {grant.created_at for grant in retried} == {_NOW}
            assert {grant.expires_at for grant in retried} == {_NOW + timedelta(minutes=5)}

            with pytest.raises(KubernetesGrantNotFoundError):
                await repository.revoke_source(
                    agent_id=uuid4(),
                    source_tool_call_id=source_tool_call_id,
                    reason="must not cross Agent ownership",
                    ended_at=_NOW + timedelta(seconds=20),
                )
            assert len(await repository.active_for_agent(agent_id=agent_id, now=_NOW)) == 2

            released_first = await repository.release(
                agent_id=agent_id,
                grant_id=grants[0].grant_id,
                reason="first scope no longer needed",
                ended_at=_NOW + timedelta(seconds=30),
            )
            assert released_first.status is KubernetesGrantStatus.RELEASED

            revoked = await repository.revoke_source(
                agent_id=agent_id,
                source_tool_call_id=source_tool_call_id,
                reason="operator ended probe",
                ended_at=_NOW + timedelta(minutes=1),
            )
            assert {grant.grant_id for grant in revoked} == {grant.grant_id for grant in grants}
            by_id = {grant.grant_id: grant for grant in revoked}
            assert by_id[grants[0].grant_id].status is KubernetesGrantStatus.RELEASED
            assert by_id[grants[0].grant_id].end_reason == "first scope no longer needed"
            assert by_id[grants[1].grant_id].status is KubernetesGrantStatus.REVOKED
            assert by_id[grants[1].grant_id].ended_at == _NOW + timedelta(minutes=1)
            assert by_id[grants[1].grant_id].end_reason == "operator ended probe"

            repeated = await repository.revoke_source(
                agent_id=agent_id,
                source_tool_call_id=source_tool_call_id,
                reason="different retry reason",
                ended_at=_NOW + timedelta(minutes=2),
            )
            assert repeated == revoked

            with pytest.raises(KubernetesGrantSourceError, match="already created a different"):
                await repository.create_many(
                    agent_id=agent_id,
                    source_tool_call_id=source_tool_call_id,
                    grants=(KubernetesGrantSpec(scope=_SCOPE, rules=(_RULE,)),),
                    created_at=_NOW + timedelta(seconds=10),
                    expires_at=_NOW + timedelta(minutes=10),
                )

            async with sessions() as session:
                rows = (
                    await session.scalars(
                        select(KubernetesGrantRow).where(KubernetesGrantRow.source_tool_call_id == source_tool_call_id)
                    )
                ).all()
                source_index = await session.scalar(
                    text(
                        "SELECT indexdef FROM pg_indexes "
                        "WHERE schemaname = current_schema() AND tablename = 'kubernetes_grants' "
                        "AND indexname = 'idx_kubernetes_grants_source_tool_call'"
                    )
                )
            assert len(rows) == 2
            assert source_index is not None
            assert "UNIQUE" not in source_index
            assert "(source_tool_call_id)" in source_index

        client.portal.call(exercise)


@pytest.mark.parametrize(
    ("scope", "rule"),
    [
        (KubernetesAllNamespacesGrantScope(), _RULE),
        (KubernetesClusterGrantScope(), _CLUSTER_RULE),
        (KubernetesNonResourceGrantScope(), _NON_RESOURCE_RULE),
    ],
)
def test_repository_persists_canonical_non_exact_scope_shapes(
    make_client: Any,
    scope: KubernetesAllNamespacesGrantScope | KubernetesClusterGrantScope | KubernetesNonResourceGrantScope,
    rule: KubernetesRule,
) -> None:
    with make_client() as client:
        app = cast(FastAPI, client.app)
        sessions = cast(async_sessionmaker[AsyncSession], app.state.db_sessions)
        assert client.portal is not None
        agent_id, binding_id = client.portal.call(_default_agent, sessions)
        source_tool_call_id = client.portal.call(partial(_source_call, sessions, binding_id=binding_id))
        repository = PostgresKubernetesGrantRepository(sessions)

        async def exercise() -> None:
            grant = await repository.create(
                agent_id=agent_id,
                source_tool_call_id=source_tool_call_id,
                scope=scope,
                rules=(rule,),
                created_at=_NOW,
                expires_at=_NOW + timedelta(minutes=5),
            )
            assert grant.scope == scope

        client.portal.call(exercise)


def test_repository_rejects_wrong_or_auto_approved_source(make_client: Any) -> None:
    with make_client() as client:
        app = cast(FastAPI, client.app)
        sessions = cast(async_sessionmaker[AsyncSession], app.state.db_sessions)
        assert client.portal is not None
        agent_id, binding_id = client.portal.call(_default_agent, sessions)
        wrong_tool = client.portal.call(partial(_source_call, sessions, binding_id=binding_id, tool_name="list_grants"))
        auto_approved = client.portal.call(
            partial(_source_call, sessions, binding_id=binding_id, approval_policy_id="unsafe-test-policy")
        )
        repository = PostgresKubernetesGrantRepository(sessions)

        async def rejected(source_tool_call_id: str) -> None:
            with pytest.raises(KubernetesGrantSourceError):
                await repository.create(
                    agent_id=agent_id,
                    source_tool_call_id=source_tool_call_id,
                    scope=_SCOPE,
                    rules=(_RULE,),
                    created_at=_NOW,
                    expires_at=_NOW + timedelta(minutes=5),
                )

        client.portal.call(rejected, wrong_tool)
        client.portal.call(rejected, auto_approved)


def test_database_rejects_grants_with_invalid_source_provenance(make_client: Any) -> None:
    with make_client() as client:
        app = cast(FastAPI, client.app)
        sessions = cast(async_sessionmaker[AsyncSession], app.state.db_sessions)
        assert client.portal is not None
        agent_id, binding_id = client.portal.call(_default_agent, sessions)
        wrong_tool = client.portal.call(partial(_source_call, sessions, binding_id=binding_id, tool_name="list_grants"))

        async def rejected() -> None:
            with pytest.raises(IntegrityError, match="invalid Kubernetes grant source provenance"):
                async with sessions.begin() as session:
                    session.add(
                        KubernetesGrantRow(
                            grant_id=uuid4(),
                            agent_id=agent_id,
                            source_tool_call_id=wrong_tool,
                            scope=_SCOPE,
                            rules=[_RULE],
                            status=KubernetesGrantStatus.ACTIVE,
                            created_at=_NOW,
                            expires_at=_NOW + timedelta(minutes=5),
                            ended_at=None,
                            end_reason=None,
                        )
                    )

        client.portal.call(rejected)


@pytest.mark.parametrize(
    ("scope", "rule"),
    [
        ({"kind": "all_namespaces"}, _RULE),
        ({"kind": "cluster"}, _CLUSTER_RULE),
        ({"kind": "non_resource"}, _NON_RESOURCE_RULE),
    ],
)
def test_database_accepts_canonical_non_exact_scope_shape(
    make_client: Any, scope: dict[str, object], rule: KubernetesRule
) -> None:
    with make_client() as client:
        app = cast(FastAPI, client.app)
        sessions = cast(async_sessionmaker[AsyncSession], app.state.db_sessions)
        assert client.portal is not None
        agent_id, binding_id = client.portal.call(_default_agent, sessions)
        source_tool_call_id = client.portal.call(partial(_source_call, sessions, binding_id=binding_id))

        client.portal.call(
            partial(
                _insert_raw_grant,
                sessions,
                agent_id=agent_id,
                source_tool_call_id=source_tool_call_id,
                scope=scope,
                rule=rule,
            )
        )


@pytest.mark.parametrize(
    "scope",
    [
        {},
        {"kind": "unknown"},
        {"kind": "namespaces"},
        {"kind": "namespaces", "namespaces": []},
        {"kind": "namespaces", "namespaces": "default"},
        {"kind": "all_namespaces", "namespaces": []},
        {"kind": "cluster", "namespaces": []},
        {"kind": "non_resource", "namespaces": []},
    ],
)
def test_database_rejects_invalid_scope_shape(make_client: Any, scope: dict[str, object]) -> None:
    with make_client() as client:
        app = cast(FastAPI, client.app)
        sessions = cast(async_sessionmaker[AsyncSession], app.state.db_sessions)
        assert client.portal is not None
        agent_id, binding_id = client.portal.call(_default_agent, sessions)
        source_tool_call_id = client.portal.call(partial(_source_call, sessions, binding_id=binding_id))

        async def rejected() -> None:
            with pytest.raises(IntegrityError, match="ck_kubernetes_grants_scope_shape"):
                await _insert_raw_grant(
                    sessions, agent_id=agent_id, source_tool_call_id=source_tool_call_id, scope=scope, rule=_RULE
                )

        client.portal.call(rejected)


if __name__ == "__main__":
    pytest_bazel.main()
