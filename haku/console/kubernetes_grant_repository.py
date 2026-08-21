"""PostgreSQL persistence for the temporary Kubernetes grant domain."""

from __future__ import annotations

import datetime
from collections.abc import Sequence
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import CursorResult, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from haku.console.agents.models import AgentStatus
from haku.console.database_schema import Agent, CredentialBinding, KubernetesGrantRow, McpToolCall, McpToolCallPrincipal
from haku.console.kubernetes_grant_models import (
    KubernetesGrant,
    KubernetesGrantNotFoundError,
    KubernetesGrantOwnershipError,
    KubernetesGrantScope,
    KubernetesGrantSourceError,
    KubernetesGrantStatus,
    KubernetesRule,
)
from haku.console.tool_calls import ToolCallStatus


class PostgresKubernetesGrantRepository:
    """Small transactional repository; all operations require an explicit Agent UUID."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    @staticmethod
    def _row_to_model(row: KubernetesGrantRow) -> KubernetesGrant:
        return KubernetesGrant(
            grant_id=row.grant_id,
            agent_id=row.agent_id,
            source_tool_call_id=row.source_tool_call_id,
            scope=row.scope,
            rules=tuple(row.rules),
            status=row.status,
            created_at=row.created_at,
            expires_at=row.expires_at,
            ended_at=row.ended_at,
            end_reason=row.end_reason,
        )

    async def _assert_agent_and_source(
        self, session: AsyncSession, *, agent_id: UUID, source_tool_call_id: str
    ) -> None:
        agent = await session.scalar(select(Agent).where(Agent.agent_id == agent_id))
        if agent is None or agent.status in (AgentStatus.ABANDONED, AgentStatus.DELETED):
            raise KubernetesGrantOwnershipError(f"Agent {agent_id} is not eligible for a Kubernetes grant")
        source = await session.scalar(
            select(McpToolCallPrincipal)
            .join(CredentialBinding, CredentialBinding.binding_id == McpToolCallPrincipal.binding_id)
            .join(McpToolCall, McpToolCall.tool_call_id == McpToolCallPrincipal.tool_call_id)
            .where(
                McpToolCallPrincipal.tool_call_id == source_tool_call_id,
                CredentialBinding.agent_id == agent_id,
                McpToolCall.server_id == "kubernetes",
                McpToolCall.tool_name == "create_grant",
                or_(McpToolCall.status == ToolCallStatus.RUNNING, McpToolCall.status == ToolCallStatus.OK),
                McpToolCall.approved_at.is_not(None),
                McpToolCall.approval_policy_id.is_(None),
            )
        )
        if source is None:
            raise KubernetesGrantSourceError(
                "source_tool_call_id must identify a manually approved kubernetes/create_grant call "
                "authenticated by the explicit Agent"
            )

    async def create(
        self,
        *,
        agent_id: UUID,
        source_tool_call_id: str,
        scope: KubernetesGrantScope,
        rules: Sequence[KubernetesRule],
        created_at: datetime.datetime,
        expires_at: datetime.datetime,
    ) -> KubernetesGrant:
        async with self._sessions.begin() as session:
            await self._assert_agent_and_source(session, agent_id=agent_id, source_tool_call_id=source_tool_call_id)
            row = KubernetesGrantRow(
                grant_id=uuid4(),
                agent_id=agent_id,
                source_tool_call_id=source_tool_call_id,
                scope=scope,
                rules=list(rules),
                status=KubernetesGrantStatus.ACTIVE,
                created_at=created_at,
                expires_at=expires_at,
                ended_at=None,
                end_reason=None,
            )
            session.add(row)
            await session.flush()
            return self._row_to_model(row)

    async def list(self, *, agent_id: UUID, include_terminal: bool = True) -> tuple[KubernetesGrant, ...]:
        async with self._sessions() as session:
            statement = select(KubernetesGrantRow).where(KubernetesGrantRow.agent_id == agent_id)
            if not include_terminal:
                statement = statement.where(KubernetesGrantRow.status == KubernetesGrantStatus.ACTIVE)
            rows = (
                await session.scalars(
                    statement.order_by(KubernetesGrantRow.created_at.desc(), KubernetesGrantRow.grant_id)
                )
            ).all()
            return tuple(self._row_to_model(row) for row in rows)

    async def get(self, *, agent_id: UUID, grant_id: UUID) -> KubernetesGrant:
        async with self._sessions() as session:
            row = await session.scalar(select(KubernetesGrantRow).where(KubernetesGrantRow.grant_id == grant_id))
            if row is None:
                raise KubernetesGrantNotFoundError(str(grant_id))
            if row.agent_id != agent_id:
                raise KubernetesGrantOwnershipError(str(grant_id))
            return self._row_to_model(row)

    async def _end(
        self, *, agent_id: UUID, grant_id: UUID, status: KubernetesGrantStatus, reason: str, ended_at: datetime.datetime
    ) -> KubernetesGrant:
        if not reason.strip():
            raise ValueError("grant end reason must not be empty")
        async with self._sessions.begin() as session:
            row = await session.scalar(
                select(KubernetesGrantRow).where(KubernetesGrantRow.grant_id == grant_id).with_for_update()
            )
            if row is None:
                raise KubernetesGrantNotFoundError(str(grant_id))
            if row.agent_id != agent_id:
                raise KubernetesGrantOwnershipError(str(grant_id))
            if row.status is KubernetesGrantStatus.ACTIVE:
                # Expiration wins over a late release/revocation attempt. This prevents a caller
                # racing the expiry sweep from reviving the meaning of an already-expired lease.
                row.status = KubernetesGrantStatus.EXPIRED if ended_at >= row.expires_at else status
                row.ended_at = ended_at
                row.end_reason = "expired" if row.status is KubernetesGrantStatus.EXPIRED else reason.strip()
                await session.flush()
            return self._row_to_model(row)

    async def release(
        self, *, agent_id: UUID, grant_id: UUID, reason: str, ended_at: datetime.datetime
    ) -> KubernetesGrant:
        return await self._end(
            agent_id=agent_id,
            grant_id=grant_id,
            status=KubernetesGrantStatus.RELEASED,
            reason=reason,
            ended_at=ended_at,
        )

    async def revoke(
        self, *, agent_id: UUID, grant_id: UUID, reason: str, ended_at: datetime.datetime
    ) -> KubernetesGrant:
        return await self._end(
            agent_id=agent_id, grant_id=grant_id, status=KubernetesGrantStatus.REVOKED, reason=reason, ended_at=ended_at
        )

    async def expire(self, *, now: datetime.datetime, agent_id: UUID | None = None) -> int:
        where = [KubernetesGrantRow.status == KubernetesGrantStatus.ACTIVE, KubernetesGrantRow.expires_at <= now]
        if agent_id is not None:
            where.append(KubernetesGrantRow.agent_id == agent_id)
        async with self._sessions.begin() as session:
            result = cast(
                CursorResult[Any],
                await session.execute(
                    update(KubernetesGrantRow)
                    .where(*where)
                    .values(status=KubernetesGrantStatus.EXPIRED, ended_at=now, end_reason="expired")
                ),
            )
            return int(result.rowcount or 0)

    async def active_for_agent(self, *, agent_id: UUID, now: datetime.datetime) -> tuple[KubernetesGrant, ...]:
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(KubernetesGrantRow)
                    .where(
                        KubernetesGrantRow.agent_id == agent_id,
                        KubernetesGrantRow.status == KubernetesGrantStatus.ACTIVE,
                        KubernetesGrantRow.expires_at > now,
                    )
                    .order_by(KubernetesGrantRow.expires_at, KubernetesGrantRow.created_at)
                )
            ).all()
            return tuple(self._row_to_model(row) for row in rows)
