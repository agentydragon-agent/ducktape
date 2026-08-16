"""Fail-closed, Console-authoritative namespace RoleBinding leases.

This is deliberately a small enforcement mechanism, not a generic Kubernetes access product.
The Console database is the authority for a lease; a managed RoleBinding is only the current
Kubernetes enforcement projection.  The projection carries a short confirmation deadline.  A
running reconciler refreshes that deadline only after it can read the durable Console record; when
the database is unavailable it removes managed bindings after the deadline rather than preserving
unverifiable elevation indefinitely.

Native RoleBindings have no TTL.  This gives fail-closed behaviour while the reconciler can reach
the Kubernetes API, but it cannot revoke access while the reconciler itself or the API is down.
High-risk access still needs an inline policy/credential gateway later.
"""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import json
import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from haku.console.database_schema import KubernetesAccessGrant
from haku.console.kube_jit_models import KubernetesAccessGrantState

logger = logging.getLogger(__name__)

MANAGED_BY_LABEL = "app.kubernetes.io/managed-by"
MANAGED_BY_VALUE = "haku-kube-jit"
LEASE_ID_ANNOTATION = "haku.allegedly.works/lease-id"
PROFILE_HASH_ANNOTATION = "haku.allegedly.works/profile-hash"
HARD_EXPIRY_ANNOTATION = "haku.allegedly.works/expires-at"
CONFIRMED_UNTIL_ANNOTATION = "haku.allegedly.works/confirmed-until"

# The initial cohort is deliberately not caller-configurable.  Haku may request a lease, but
# cannot use the request API to substitute a different human, group, or ServiceAccount.
FIXED_SUBJECTS = (
    {"kind": "Group", "apiGroup": "rbac.authorization.k8s.io", "name": "oidc-ksbx-groups:haku"},
    {"kind": "ServiceAccount", "name": "haku", "namespace": "haku-sandbox"},
    {"kind": "ServiceAccount", "name": "haku-claude", "namespace": "haku-claude-sandbox"},
)


class AccessProfile(BaseModel):
    """A deploy-reviewed namespace access profile.

    The role is intentionally a ClusterRole, bound through a namespace RoleBinding.  This permits
    one reviewed profile definition to be reused in explicit namespaces without granting any
    cluster-scoped resource access.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,62}$")
    description: str = Field(min_length=1, max_length=500)
    cluster_role: str = Field(min_length=1, max_length=253)
    namespaces: tuple[str, ...] = Field(min_length=1)
    max_duration_seconds: int = Field(ge=60, le=86_400)

    @field_validator("namespaces")
    @classmethod
    def _namespaces_are_distinct_dns_labels(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("namespaces must not contain duplicates")
        for namespace in value:
            if not namespace or len(namespace) > 63:
                raise ValueError("namespace must be a non-empty DNS label")
        return value

    @property
    def revision_hash(self) -> str:
        """Stable content hash captured in both the DB record and RoleBinding annotation."""
        canonical = json.dumps(self.model_dump(mode="json"), separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()


class KubeJitConfig(BaseModel):
    """Non-secret deploy configuration for the lease authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    profiles: tuple[AccessProfile, ...] = ()
    confirmation_window_seconds: int = Field(default=300, ge=30, le=3600)
    reconcile_interval_seconds: int = Field(default=30, ge=5, le=300)

    @field_validator("profiles")
    @classmethod
    def _profile_ids_are_distinct(cls, value: tuple[AccessProfile, ...]) -> tuple[AccessProfile, ...]:
        ids = [profile.id for profile in value]
        if len(set(ids)) != len(ids):
            raise ValueError("kube_jit profile ids must be unique")
        return value

    def profile(self, profile_id: str) -> AccessProfile:
        for profile in self.profiles:
            if profile.id == profile_id:
                return profile
        raise ValueError(f"unknown Kubernetes access profile {profile_id!r}")


@dataclass(frozen=True, slots=True)
class Grant:
    lease_id: UUID
    tool_call_id: str
    operator_id: UUID
    requester: str
    profile_id: str
    profile_hash: str
    namespace: str
    cluster_role: str
    issued_at: datetime.datetime
    expires_at: datetime.datetime
    state: KubernetesAccessGrantState
    revoked_at: datetime.datetime | None = None

    @property
    def role_binding_name(self) -> str:
        return f"haku-jit-{self.lease_id.hex}"


class GrantStore(Protocol):
    async def create(
        self,
        *,
        tool_call_id: str,
        operator_id: UUID,
        requester: str,
        profile: AccessProfile,
        namespace: str,
        duration_seconds: int,
        now: datetime.datetime,
    ) -> Grant: ...

    async def revoke(self, *, lease_id: UUID, now: datetime.datetime) -> Grant: ...

    async def get(self, lease_id: UUID) -> Grant | None: ...

    async def active(self, *, now: datetime.datetime) -> list[Grant]: ...

    async def expire_due(self, *, now: datetime.datetime) -> None: ...


class PostgresGrantStore:
    """The durable Console lease ledger.  Kubernetes state is intentionally not authoritative."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create(
        self,
        *,
        tool_call_id: str,
        operator_id: UUID,
        requester: str,
        profile: AccessProfile,
        namespace: str,
        duration_seconds: int,
        now: datetime.datetime,
    ) -> Grant:
        if namespace not in profile.namespaces:
            raise ValueError(f"profile {profile.id!r} is not allowed in namespace {namespace!r}")
        if duration_seconds > profile.max_duration_seconds:
            raise ValueError(f"duration exceeds {profile.id!r} maximum of {profile.max_duration_seconds} seconds")
        issued_at = _utc(now)
        row = KubernetesAccessGrant(
            lease_id=uuid4(),
            tool_call_id=tool_call_id,
            operator_id=operator_id,
            requester=requester,
            profile_id=profile.id,
            profile_hash=profile.revision_hash,
            namespace=namespace,
            cluster_role=profile.cluster_role,
            issued_at=issued_at,
            expires_at=issued_at + datetime.timedelta(seconds=duration_seconds),
            state=KubernetesAccessGrantState.PENDING,
            revoked_at=None,
        )
        async with self._sessions.begin() as session:
            session.add(row)
        return _grant_from_row(row)

    async def revoke(self, *, lease_id: UUID, now: datetime.datetime) -> Grant:
        async with self._sessions.begin() as session:
            row = await session.get(KubernetesAccessGrant, lease_id, with_for_update=True)
            if row is None:
                raise LookupError("Kubernetes access grant not found")
            if row.state in {KubernetesAccessGrantState.REVOKED, KubernetesAccessGrantState.EXPIRED}:
                return _grant_from_row(row)
            row.state = KubernetesAccessGrantState.REVOKED
            row.revoked_at = _utc(now)
        return _grant_from_row(row)

    async def get(self, lease_id: UUID) -> Grant | None:
        async with self._sessions() as session:
            row = await session.get(KubernetesAccessGrant, lease_id)
            return _grant_from_row(row) if row is not None else None

    async def active(self, *, now: datetime.datetime) -> list[Grant]:
        await self.expire_due(now=now)
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(KubernetesAccessGrant).where(
                        KubernetesAccessGrant.state == KubernetesAccessGrantState.ACTIVE
                    )
                )
            ).all()
            return [_grant_from_row(row) for row in rows]

    async def expire_due(self, *, now: datetime.datetime) -> None:
        instant = _utc(now)
        async with self._sessions.begin() as session:
            rows = (
                await session.scalars(
                    select(KubernetesAccessGrant)
                    .where(
                        KubernetesAccessGrant.state.in_(
                            (KubernetesAccessGrantState.PENDING, KubernetesAccessGrantState.ACTIVE)
                        )
                    )
                    .where(KubernetesAccessGrant.expires_at <= instant)
                    .with_for_update()
                )
            ).all()
            for row in rows:
                row.state = KubernetesAccessGrantState.EXPIRED

    async def activate(self, *, lease_id: UUID) -> None:
        """Mark an applied lease active.  Kept out of the public port: only the reconciler calls it."""
        async with self._sessions.begin() as session:
            row = await session.get(KubernetesAccessGrant, lease_id, with_for_update=True)
            if row is not None and row.state is KubernetesAccessGrantState.PENDING:
                row.state = KubernetesAccessGrantState.ACTIVE


class RoleBindingClient(Protocol):
    async def apply(self, grant: Grant, *, confirmed_until: datetime.datetime) -> None: ...

    async def delete(self, *, namespace: str, name: str) -> None: ...

    async def managed(self, namespaces: Sequence[str]) -> list[dict[str, object]]: ...

    async def aclose(self) -> None: ...


class LeaseReconciler:
    """Projects active grants to RoleBindings and fails closed when authority cannot be read."""

    def __init__(self, *, config: KubeJitConfig, grants: GrantStore, role_bindings: RoleBindingClient) -> None:
        self._config = config
        self._grants = grants
        self._role_bindings = role_bindings

    async def reconcile_once(self, *, now: datetime.datetime) -> None:
        instant = _utc(now)
        try:
            active = await self._grants.active(now=instant)
        except Exception:
            # Do not leave a prior positive DB read valid indefinitely.  A managed binding has its
            # own short confirmation deadline exactly for this failure mode.
            logger.exception("kube-jit authority read failed; reaping stale managed RoleBindings")
            await self._reap_unconfirmed(now=instant)
            return

        desired = {grant.lease_id: grant for grant in active if grant.expires_at > instant}
        confirmed_until = instant + datetime.timedelta(seconds=self._config.confirmation_window_seconds)
        for grant in desired.values():
            await self._role_bindings.apply(grant, confirmed_until=min(confirmed_until, grant.expires_at))
            # The lease was persisted before the call.  This status is merely observed projection
            # progress; a crash before it is written simply retries idempotently next cycle.
            activate = getattr(self._grants, "activate", None)
            if activate is not None:
                await activate(lease_id=grant.lease_id)

        for binding in await self._role_bindings.managed(_configured_namespaces(self._config)):
            lease_id = _binding_lease_id(binding)
            metadata = _binding_metadata(binding)
            namespace = metadata.get("namespace")
            name = metadata.get("name")
            if not isinstance(namespace, str) or not isinstance(name, str):
                continue
            expected = desired.get(lease_id) if lease_id is not None else None
            if expected is None or not _binding_matches_grant(binding, expected):
                await self._role_bindings.delete(namespace=namespace, name=name)

    async def _reap_unconfirmed(self, *, now: datetime.datetime) -> None:
        for binding in await self._role_bindings.managed(_configured_namespaces(self._config)):
            metadata = _binding_metadata(binding)
            namespace, name = metadata.get("namespace"), metadata.get("name")
            if not isinstance(namespace, str) or not isinstance(name, str):
                continue
            deadline = _annotation_time(binding, CONFIRMED_UNTIL_ANNOTATION)
            hard_expiry = _annotation_time(binding, HARD_EXPIRY_ANNOTATION)
            # Missing/malformed authority metadata is an unverifiable managed binding, so do not
            # wait for an attacker-controlled or absent clock value.
            if deadline is None or hard_expiry is None or deadline <= now or hard_expiry <= now:
                await self._role_bindings.delete(namespace=namespace, name=name)

    @asynccontextmanager
    async def run(self) -> AsyncIterator[None]:
        """Run a bounded, cancellation-safe reconciliation loop for the Console lifespan."""
        task = asyncio.create_task(self._run_forever())
        try:
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await self._role_bindings.aclose()

    async def _run_forever(self) -> None:
        while True:
            try:
                await self.reconcile_once(now=datetime.datetime.now(datetime.UTC))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("kube-jit reconciliation failed")
            await asyncio.sleep(self._config.reconcile_interval_seconds)


def role_binding_manifest(grant: Grant, *, confirmed_until: datetime.datetime) -> dict[str, object]:
    """Build the only native authorization object this phase may create."""
    return {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "RoleBinding",
        "metadata": {
            "name": grant.role_binding_name,
            "namespace": grant.namespace,
            "labels": {MANAGED_BY_LABEL: MANAGED_BY_VALUE},
            "annotations": {
                LEASE_ID_ANNOTATION: str(grant.lease_id),
                PROFILE_HASH_ANNOTATION: grant.profile_hash,
                HARD_EXPIRY_ANNOTATION: _format_time(grant.expires_at),
                CONFIRMED_UNTIL_ANNOTATION: _format_time(confirmed_until),
            },
        },
        "subjects": list(FIXED_SUBJECTS),
        "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole", "name": grant.cluster_role},
    }


def _configured_namespaces(config: KubeJitConfig) -> tuple[str, ...]:
    return tuple(sorted({namespace for profile in config.profiles for namespace in profile.namespaces}))


def _binding_metadata(binding: dict[str, object]) -> dict[str, object]:
    value = binding.get("metadata")
    return value if isinstance(value, dict) else {}


def _binding_lease_id(binding: dict[str, object]) -> UUID | None:
    annotations = _binding_metadata(binding).get("annotations")
    if not isinstance(annotations, dict):
        return None
    value = annotations.get(LEASE_ID_ANNOTATION)
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _binding_matches_grant(binding: dict[str, object], grant: Grant) -> bool:
    metadata = _binding_metadata(binding)
    annotations = metadata.get("annotations")
    role_ref = binding.get("roleRef")
    return (
        metadata.get("name") == grant.role_binding_name
        and metadata.get("namespace") == grant.namespace
        and isinstance(annotations, dict)
        and annotations.get(PROFILE_HASH_ANNOTATION) == grant.profile_hash
        and isinstance(role_ref, dict)
        and role_ref == {"apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole", "name": grant.cluster_role}
        and binding.get("subjects") == list(FIXED_SUBJECTS)
    )


def _annotation_time(binding: dict[str, object], key: str) -> datetime.datetime | None:
    annotations = _binding_metadata(binding).get("annotations")
    value = annotations.get(key) if isinstance(annotations, dict) else None
    if not isinstance(value, str):
        return None
    try:
        return _utc(datetime.datetime.fromisoformat(value))
    except ValueError:
        return None


def _format_time(value: datetime.datetime) -> str:
    return _utc(value).isoformat(timespec="seconds").replace("+00:00", "Z")


def _utc(value: datetime.datetime) -> datetime.datetime:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(datetime.UTC)


def _grant_from_row(row: KubernetesAccessGrant) -> Grant:
    return Grant(
        lease_id=row.lease_id,
        tool_call_id=row.tool_call_id,
        operator_id=row.operator_id,
        requester=row.requester,
        profile_id=row.profile_id,
        profile_hash=row.profile_hash,
        namespace=row.namespace,
        cluster_role=row.cluster_role,
        issued_at=row.issued_at,
        expires_at=row.expires_at,
        state=row.state,
        revoked_at=row.revoked_at,
    )
