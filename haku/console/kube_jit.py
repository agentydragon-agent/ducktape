"""Console-authoritative, explicit-policy temporary namespace RBAC leases.

A Console grant stores the *canonical PolicyRule list that was approved*. The Console never
creates Kubernetes RBAC objects. A separately deployed reconciler reads this durable ledger and
projects each active lease to a lease-named Role plus a fixed-cohort RoleBinding.

The worker is intentionally a separate security and availability domain: it continues expiry and
revocation processing through Console API crashes/restarts. Kubernetes requires a controller that
creates arbitrary Roles to hold `escalate`; that broad capability is confined to this dedicated
ServiceAccount and guarded by the policy validation below, never handed to Haku or the Console.
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
from typing import Any, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from haku.console.database_schema import KubernetesAccessGrant
from haku.console.kube_jit_models import KubernetesAccessGrantState

logger = logging.getLogger(__name__)

MANAGED_BY_LABEL = "app.kubernetes.io/managed-by"
MANAGED_BY_VALUE = "haku-kube-jit"
LEASE_ID_ANNOTATION = "haku.allegedly.works/lease-id"
POLICY_HASH_ANNOTATION = "haku.allegedly.works/policy-hash"
HARD_EXPIRY_ANNOTATION = "haku.allegedly.works/expires-at"
CONFIRMED_UNTIL_ANNOTATION = "haku.allegedly.works/confirmed-until"

# Haku may request an explicit policy but never pick who receives it.
FIXED_SUBJECTS = (
    {"kind": "Group", "apiGroup": "rbac.authorization.k8s.io", "name": "oidc-ksbx-groups:haku"},
    {"kind": "ServiceAccount", "name": "haku", "namespace": "haku-sandbox"},
    {"kind": "ServiceAccount", "name": "haku-claude", "namespace": "haku-claude-sandbox"},
)
_FORBIDDEN_RESOURCES = frozenset({"secrets", "roles", "rolebindings", "clusterroles", "clusterrolebindings"})
_FORBIDDEN_VERBS = frozenset({"bind", "escalate", "impersonate"})


class PolicyRule(BaseModel):
    """A deliberately conservative, namespaced Kubernetes RBAC rule.

    Wildcards are prohibited rather than being normalized: approvals must display a finite,
    concrete permission set. `nonResourceURLs` and cluster-scoped resources are out of phase one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    api_groups: tuple[str, ...] = Field(min_length=1)
    resources: tuple[str, ...] = Field(min_length=1)
    verbs: tuple[str, ...] = Field(min_length=1)
    resource_names: tuple[str, ...] = ()

    @field_validator("api_groups", "resources", "verbs", "resource_names")
    @classmethod
    def _deduplicate_and_reject_wildcards(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("rule values must not contain duplicates")
        if any(not item or item == "*" for item in value):
            raise ValueError("empty values and wildcards are prohibited in temporary access rules")
        return tuple(sorted(value))

    @model_validator(mode="after")
    def _limit_phase_one_surface(self) -> PolicyRule:
        if _FORBIDDEN_RESOURCES.intersection(self.resources):
            raise ValueError("temporary access rules cannot grant Secrets or RBAC management")
        if _FORBIDDEN_VERBS.intersection(self.verbs):
            raise ValueError("temporary access rules cannot grant bind, escalate, or impersonate")
        return self

    def as_kubernetes(self) -> dict[str, object]:
        result: dict[str, object] = {"apiGroups": list(self.api_groups), "resources": list(self.resources), "verbs": list(self.verbs)}
        if self.resource_names:
            result["resourceNames"] = list(self.resource_names)
        return result


class KubeJitConfig(BaseModel):
    """Deploy-reviewed guardrails, not a catalog of granted permissions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    namespaces: tuple[str, ...] = Field(min_length=1)
    max_duration_seconds: int = Field(default=3600, ge=60, le=86_400)
    confirmation_window_seconds: int = Field(default=300, ge=30, le=3600)
    reconcile_interval_seconds: int = Field(default=30, ge=5, le=300)

    @field_validator("namespaces")
    @classmethod
    def _valid_namespaces(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value) or any(not namespace or len(namespace) > 63 for namespace in value):
            raise ValueError("namespaces must be distinct non-empty DNS labels")
        return tuple(sorted(value))


@dataclass(frozen=True, slots=True)
class Grant:
    lease_id: UUID
    namespace: str
    rules: tuple[PolicyRule, ...]
    policy_hash: str
    issued_at: datetime.datetime
    expires_at: datetime.datetime
    state: KubernetesAccessGrantState
    revoked_at: datetime.datetime | None = None

    @property
    def role_name(self) -> str:
        return f"haku-jit-{self.lease_id.hex}"

    @property
    def role_binding_name(self) -> str:
        return self.role_name


class GrantStore(Protocol):
    async def create(
        self, *, namespace: str, rules: tuple[PolicyRule, ...], duration_seconds: int, now: datetime.datetime
    ) -> Grant: ...
    async def revoke(self, *, lease_id: UUID, now: datetime.datetime) -> Grant: ...
    async def get(self, lease_id: UUID) -> Grant | None: ...
    async def active(self, *, now: datetime.datetime) -> list[Grant]: ...
    async def expire_due(self, *, now: datetime.datetime) -> None: ...


class PostgresGrantStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], config: KubeJitConfig) -> None:
        self._sessions, self._config = sessions, config

    async def create(self, *, namespace: str, rules: tuple[PolicyRule, ...], duration_seconds: int, now: datetime.datetime) -> Grant:
        if namespace not in self._config.namespaces:
            raise ValueError(f"temporary access is not allowed in namespace {namespace!r}")
        if duration_seconds > self._config.max_duration_seconds:
            raise ValueError(f"duration exceeds maximum of {self._config.max_duration_seconds} seconds")
        if not rules:
            raise ValueError("at least one explicit policy rule is required")
        canonical_rules = tuple(sorted(rules, key=lambda rule: json.dumps(rule.model_dump(mode="json"), sort_keys=True)))
        instant = _utc(now)
        row = KubernetesAccessGrant(
            lease_id=uuid4(), namespace=namespace, policy_rules=[rule.model_dump(mode="json") for rule in canonical_rules],
            policy_hash=_policy_hash(canonical_rules), issued_at=instant,
            expires_at=instant + datetime.timedelta(seconds=duration_seconds), state=KubernetesAccessGrantState.PENDING, revoked_at=None,
        )
        async with self._sessions.begin() as session:
            session.add(row)
        return _grant_from_row(row)

    async def revoke(self, *, lease_id: UUID, now: datetime.datetime) -> Grant:
        async with self._sessions.begin() as session:
            row = await session.get(KubernetesAccessGrant, lease_id, with_for_update=True)
            if row is None:
                raise LookupError("Kubernetes access grant not found")
            if row.state not in {KubernetesAccessGrantState.REVOKED, KubernetesAccessGrantState.EXPIRED}:
                row.state, row.revoked_at = KubernetesAccessGrantState.REVOKED, _utc(now)
        return _grant_from_row(row)

    async def get(self, lease_id: UUID) -> Grant | None:
        async with self._sessions() as session:
            row = await session.get(KubernetesAccessGrant, lease_id)
            return _grant_from_row(row) if row else None

    async def active(self, *, now: datetime.datetime) -> list[Grant]:
        await self.expire_due(now=now)
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(KubernetesAccessGrant).where(
                        KubernetesAccessGrant.state.in_(
                            (KubernetesAccessGrantState.PENDING, KubernetesAccessGrantState.ACTIVE)
                        )
                    )
                )
            ).all()
            return [_grant_from_row(row) for row in rows]

    async def expire_due(self, *, now: datetime.datetime) -> None:
        async with self._sessions.begin() as session:
            rows = (await session.scalars(select(KubernetesAccessGrant).where(KubernetesAccessGrant.state.in_((KubernetesAccessGrantState.PENDING, KubernetesAccessGrantState.ACTIVE))).where(KubernetesAccessGrant.expires_at <= _utc(now)).with_for_update())).all()
            for row in rows:
                row.state = KubernetesAccessGrantState.EXPIRED

    async def activate(self, *, lease_id: UUID) -> None:
        async with self._sessions.begin() as session:
            row = await session.get(KubernetesAccessGrant, lease_id, with_for_update=True)
            if row and row.state == KubernetesAccessGrantState.PENDING:
                row.state = KubernetesAccessGrantState.ACTIVE


class AccessClient(Protocol):
    async def apply(self, grant: Grant, *, confirmed_until: datetime.datetime) -> None: ...
    async def delete(self, *, namespace: str, name: str) -> None: ...
    async def managed(self, namespaces: Sequence[str]) -> list[dict[str, object]]: ...
    async def aclose(self) -> None: ...


class LeaseReconciler:
    def __init__(self, *, config: KubeJitConfig, grants: GrantStore, access: AccessClient) -> None:
        self._config, self._grants, self._access = config, grants, access

    async def reconcile_once(self, *, now: datetime.datetime) -> None:
        instant = _utc(now)
        try:
            desired = {grant.lease_id: grant for grant in await self._grants.active(now=instant) if grant.expires_at > instant}
        except Exception:
            logger.exception("kube-jit authority read failed; reaping stale managed RBAC")
            await self._reap_unconfirmed(now=instant)
            return
        deadline = instant + datetime.timedelta(seconds=self._config.confirmation_window_seconds)
        for grant in desired.values():
            await self._access.apply(grant, confirmed_until=min(deadline, grant.expires_at))
            activate = getattr(self._grants, "activate", None)
            if activate:
                await activate(lease_id=grant.lease_id)
        for resource in await self._access.managed(self._config.namespaces):
            metadata = _metadata(resource)
            namespace, name, lease_id = metadata.get("namespace"), metadata.get("name"), _lease_id(resource)
            expected = desired.get(lease_id) if lease_id else None
            if isinstance(namespace, str) and isinstance(name, str) and (expected is None or not _matches(resource, expected)):
                await self._access.delete(namespace=namespace, name=name)

    async def _reap_unconfirmed(self, *, now: datetime.datetime) -> None:
        for resource in await self._access.managed(self._config.namespaces):
            metadata = _metadata(resource)
            namespace, name = metadata.get("namespace"), metadata.get("name")
            if isinstance(namespace, str) and isinstance(name, str):
                deadline, expiry = _annotation_time(resource, CONFIRMED_UNTIL_ANNOTATION), _annotation_time(resource, HARD_EXPIRY_ANNOTATION)
                if deadline is None or expiry is None or deadline <= now or expiry <= now:
                    await self._access.delete(namespace=namespace, name=name)

    @asynccontextmanager
    async def run(self) -> AsyncIterator[None]:
        task = asyncio.create_task(self._run_forever())
        try:
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await self._access.aclose()

    async def _run_forever(self) -> None:
        while True:
            try:
                await self.reconcile_once(now=datetime.datetime.now(datetime.UTC))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("kube-jit reconciliation failed")
            await asyncio.sleep(self._config.reconcile_interval_seconds)


def role_manifest(grant: Grant, *, confirmed_until: datetime.datetime) -> dict[str, object]:
    return {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "Role", "metadata": _metadata_for(grant, confirmed_until), "rules": [rule.as_kubernetes() for rule in grant.rules]}


def role_binding_manifest(grant: Grant, *, confirmed_until: datetime.datetime) -> dict[str, object]:
    return {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "RoleBinding", "metadata": _metadata_for(grant, confirmed_until), "subjects": list(FIXED_SUBJECTS), "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": grant.role_name}}


def _metadata_for(grant: Grant, confirmed_until: datetime.datetime) -> dict[str, object]:
    return {"name": grant.role_name, "namespace": grant.namespace, "labels": {MANAGED_BY_LABEL: MANAGED_BY_VALUE}, "annotations": {LEASE_ID_ANNOTATION: str(grant.lease_id), POLICY_HASH_ANNOTATION: grant.policy_hash, HARD_EXPIRY_ANNOTATION: _format_time(grant.expires_at), CONFIRMED_UNTIL_ANNOTATION: _format_time(confirmed_until)}}

def _metadata(value: dict[str, object]) -> dict[str, object]:
    candidate = value.get("metadata")
    return candidate if isinstance(candidate, dict) else {}

def _lease_id(value: dict[str, object]) -> UUID | None:
    annotations = _metadata(value).get("annotations")
    try:
        return UUID(annotations[LEASE_ID_ANNOTATION]) if isinstance(annotations, dict) and isinstance(annotations.get(LEASE_ID_ANNOTATION), str) else None
    except ValueError:
        return None

def _matches(value: dict[str, object], grant: Grant) -> bool:
    annotations = _metadata(value).get("annotations")
    return _metadata(value).get("namespace") == grant.namespace and _metadata(value).get("name") == grant.role_name and isinstance(annotations, dict) and annotations.get(POLICY_HASH_ANNOTATION) == grant.policy_hash

def _annotation_time(value: dict[str, object], key: str) -> datetime.datetime | None:
    annotations = _metadata(value).get("annotations")
    try:
        return _utc(datetime.datetime.fromisoformat(annotations[key])) if isinstance(annotations, dict) and isinstance(annotations.get(key), str) else None
    except ValueError:
        return None

def _policy_hash(rules: tuple[PolicyRule, ...]) -> str:
    return hashlib.sha256(json.dumps([rule.model_dump(mode="json") for rule in rules], separators=(",", ":"), sort_keys=True).encode()).hexdigest()
def _format_time(value: datetime.datetime) -> str:
    return _utc(value).isoformat(timespec="seconds").replace("+00:00", "Z")
def _utc(value: datetime.datetime) -> datetime.datetime:
    if value.tzinfo is None: raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(datetime.UTC)
def _grant_from_row(row: KubernetesAccessGrant) -> Grant:
    rules = tuple(PolicyRule.model_validate(rule) for rule in row.policy_rules)
    return Grant(lease_id=row.lease_id, namespace=row.namespace, rules=rules, policy_hash=row.policy_hash, issued_at=row.issued_at, expires_at=row.expires_at, state=row.state, revoked_at=row.revoked_at)
