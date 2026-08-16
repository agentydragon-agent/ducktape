"""Approval-gated Console requests for explicit temporary Kubernetes policy rules."""

from __future__ import annotations

import datetime
from typing import Annotated
from uuid import UUID

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from haku.console.kube_jit import Grant, GrantStore, PolicyRule

KUBE_JIT_SERVER_ID = "kube-jit"


class GrantResult(BaseModel):
    lease_id: UUID
    namespace: str
    policy_hash: str
    expires_at: datetime.datetime
    state: str


def _result(grant: Grant) -> GrantResult:
    return GrantResult(
        lease_id=grant.lease_id,
        namespace=grant.namespace,
        policy_hash=grant.policy_hash,
        expires_at=grant.expires_at,
        state=grant.state,
    )


class KubeJitGrantService:
    def __init__(self, *, grants: GrantStore) -> None:
        self._grants = grants

    async def request(self, *, namespace: str, rules: list[PolicyRule], duration_seconds: int, reason: str) -> GrantResult:
        if not reason.strip():
            raise ValueError("reason must not be blank")
        grant = await self._grants.create(
            namespace=namespace, rules=tuple(rules), duration_seconds=duration_seconds, now=datetime.datetime.now(datetime.UTC)
        )
        return _result(grant)

    async def revoke(self, lease_id: UUID) -> GrantResult:
        # The approval ledger already records who requested and approved this action. The lease
        # table is deliberately enforcement state, not a second competing audit trail.
        return _result(await self._grants.revoke(lease_id=lease_id, now=datetime.datetime.now(datetime.UTC)))

    async def list(self) -> list[GrantResult]:
        return [_result(grant) for grant in await self._grants.active(now=datetime.datetime.now(datetime.UTC))]


def build_mcp(service: KubeJitGrantService) -> FastMCP:
    mcp = FastMCP(name=KUBE_JIT_SERVER_ID, instructions=(
        "Request, inspect, or revoke explicit, namespace-scoped Kubernetes PolicyRule leases. The exact rules, "
        "namespace, reason, approval, and expiry are recorded in Haku Console's tool-call ledger. A separate trusted "
        "worker creates a lease-named Role and fixed-subject RoleBinding; Haku cannot choose subjects or write RBAC."
    ))

    @mcp.tool
    async def request_access(
        namespace: Annotated[str, Field(description="Target namespace; must be in the deploy-reviewed allowlist.")],
        rules: Annotated[list[PolicyRule], Field(min_length=1, max_length=32, description="Exact Kubernetes PolicyRule objects to approve. Wildcards, Secrets, RBAC management, bind/escalate, and impersonation are rejected.")],
        duration_seconds: Annotated[int, Field(ge=60, le=86_400, description="Requested lease duration in seconds.")],
        reason: Annotated[str, Field(min_length=1, max_length=2000, description="Why these exact permissions are needed.")],
    ) -> GrantResult:
        return await service.request(namespace=namespace, rules=rules, duration_seconds=duration_seconds, reason=reason)

    @mcp.tool
    async def list_access() -> list[GrantResult]:
        """List every current, non-expired temporary access lease."""
        return await service.list()

    @mcp.tool
    async def revoke_access(lease_id: Annotated[UUID, Field(description="Lease ID returned by request_access.")]) -> GrantResult:
        return await service.revoke(lease_id)

    return mcp
