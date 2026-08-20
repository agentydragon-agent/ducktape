"""PostgreSQL lifecycle and provenance tests for temporary Kubernetes grants."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
import pytest_bazel
from fastapi import FastAPI
from sqlalchemy import select
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
from haku.console.kubernetes_grant_models import KubernetesGrantSourceError, KubernetesGrantStatus, KubernetesRule
from haku.console.kubernetes_grant_repository import PostgresKubernetesGrantRepository
from haku.console.tool_calls import ToolCallStatus

_NOW = datetime(2026, 8, 20, 0, 0, tzinfo=UTC)
_RULE = KubernetesRule(api_groups=("",), resources=("pods",), verbs=("get",))


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
                            rules=[_RULE],
                            status=KubernetesGrantStatus.ACTIVE,
                            created_at=_NOW,
                            expires_at=_NOW + timedelta(minutes=5),
                            ended_at=None,
                            end_reason=None,
                        )
                    )

        client.portal.call(rejected)


if __name__ == "__main__":
    pytest_bazel.main()
