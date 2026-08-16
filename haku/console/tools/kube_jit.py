"""Approval-gated Console requests for temporary namespaced Kubernetes access."""

from __future__ import annotations

import datetime
from typing import Annotated
from uuid import UUID

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from haku.console.kube_jit import GrantStore, KubeJitConfig
from haku.console.tool_execution_context import current_tool_execution

KUBE_JIT_SERVER_ID = "kube-jit"


class GrantResult(BaseModel):
    lease_id: str
    namespace: str
    profile: str
    expires_at: datetime.datetime
    state: str


class KubeJitGrantService:
    def __init__(self, *, config: KubeJitConfig, grants: GrantStore) -> None:
        self._config = config
        self._grants = grants

    async def request(self, *, profile_id: str, namespace: str, duration_seconds: int, reason: str) -> GrantResult:
        context = current_tool_execution.get()
        if context is None:
            raise RuntimeError("kube-jit requests must execute through the Console approval ledger")
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValueError("reason must not be blank")
        profile = self._config.profile(profile_id)
        grant = await self._grants.create(
            tool_call_id=context.tool_call_id,
            operator_id=context.operator_id,
            requester=context.requester,
            profile=profile,
            namespace=namespace,
            duration_seconds=duration_seconds,
            now=datetime.datetime.now(datetime.UTC),
        )
        return GrantResult(
            lease_id=str(grant.lease_id),
            namespace=grant.namespace,
            profile=grant.profile_id,
            expires_at=grant.expires_at,
            state=grant.state,
        )

    async def revoke(self, lease_id: str) -> GrantResult:
        context = current_tool_execution.get()
        if context is None:
            raise RuntimeError("kube-jit revocations must execute through the Console approval ledger")
        parsed_lease_id = UUID(lease_id)
        existing = await self._grants.get(parsed_lease_id)
        if existing is None:
            raise LookupError("Kubernetes access grant not found")
        if existing.operator_id != context.operator_id:
            raise PermissionError("a Console operator may revoke only its own Kubernetes access grants")
        grant = await self._grants.revoke(lease_id=parsed_lease_id, now=datetime.datetime.now(datetime.UTC))
        # The durable revocation is committed before this returns. The reconciler's pull loop is
        # the delivery backstop; it does not rely on a best-effort direct Kubernetes delete here.
        return GrantResult(
            lease_id=str(grant.lease_id),
            namespace=grant.namespace,
            profile=grant.profile_id,
            expires_at=grant.expires_at,
            state=grant.state,
        )


def build_mcp(service: KubeJitGrantService) -> FastMCP:
    mcp = FastMCP(
        name=KUBE_JIT_SERVER_ID,
        instructions=(
            "Request or revoke a reviewed, namespace-scoped Kubernetes access lease. Every mutation "
            "is first persisted in Haku Console's approval/audit ledger and requires operator approval. "
            "Haku cannot choose grant subjects or write Kubernetes RoleBindings directly."
        ),
    )

    @mcp.tool
    async def request_access(
        profile: Annotated[str, Field(description="Deploy-reviewed access profile ID.")],
        namespace: Annotated[str, Field(description="Namespace explicitly allowed by the selected profile.")],
        duration_seconds: Annotated[int, Field(ge=60, le=86_400, description="Requested lease duration in seconds.")],
        reason: Annotated[str, Field(min_length=1, max_length=2000, description="Why this bounded access is needed.")],
    ) -> GrantResult:
        return await service.request(
            profile_id=profile, namespace=namespace, duration_seconds=duration_seconds, reason=reason
        )

    @mcp.tool
    async def revoke_access(
        lease_id: Annotated[str, Field(description="Lease ID returned by request_access.")],
    ) -> GrantResult:
        return await service.revoke(lease_id)

    return mcp
