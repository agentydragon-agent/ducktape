from __future__ import annotations

import datetime
from collections.abc import Sequence
from typing import Any, cast
from uuid import UUID

import pytest

from haku.console.kube_jit import (
    CONFIRMED_UNTIL_ANNOTATION,
    FIXED_SUBJECTS,
    AccessClient,
    Grant,
    GrantStore,
    KubernetesAccessGrantState,
    KubeJitConfig,
    LeaseReconciler,
    PolicyRule,
    role_binding_manifest,
    role_manifest,
)

NOW = datetime.datetime(2026, 8, 16, tzinfo=datetime.UTC)
RULE = PolicyRule(api_groups=("apps",), resources=("deployments",), verbs=("get", "list"))
CONFIG = KubeJitConfig(namespaces=("target",), confirmation_window_seconds=120)


def _grant() -> Grant:
    return Grant(
        lease_id=UUID("11111111-1111-1111-1111-111111111111"), namespace="target",
        rules=(RULE,), policy_hash="policy-hash", issued_at=NOW, expires_at=NOW + datetime.timedelta(minutes=10),
        state=KubernetesAccessGrantState.ACTIVE,
    )


class FakeGrants:
    def __init__(self, grants: list[Grant], *, fails: bool = False) -> None:
        self.grants, self.fails, self.activated = grants, fails, []

    async def create(self, **kwargs: Any) -> Grant: raise AssertionError(kwargs)
    async def revoke(self, **kwargs: Any) -> Grant: raise AssertionError(kwargs)
    async def get(self, lease_id: UUID) -> Grant | None: return next((g for g in self.grants if g.lease_id == lease_id), None)
    async def active(self, *, now: datetime.datetime) -> list[Grant]:
        if self.fails: raise ConnectionError("Console DB unavailable")
        return self.grants
    async def expire_due(self, *, now: datetime.datetime) -> None: pass
    async def activate(self, *, lease_id: UUID) -> None: self.activated.append(lease_id)


class FakeAccess(AccessClient):
    def __init__(self, resources: list[dict[str, Any]] | None = None) -> None:
        self.resources, self.applied, self.deleted = resources or [], [], []
    async def apply(self, grant: Grant, *, confirmed_until: datetime.datetime) -> None: self.applied.append(grant)
    async def delete(self, *, namespace: str, name: str) -> None: self.deleted.append((namespace, name))
    async def managed(self, namespaces: Sequence[str]) -> list[dict[str, object]]: return self.resources
    async def aclose(self) -> None: pass


def test_explicit_rules_make_a_lease_named_role_and_fixed_subject_binding() -> None:
    grant = _grant()
    role = cast(dict[str, Any], role_manifest(grant, confirmed_until=NOW + datetime.timedelta(minutes=2)))
    binding = cast(dict[str, Any], role_binding_manifest(grant, confirmed_until=NOW + datetime.timedelta(minutes=2)))
    assert role["rules"] == [{"apiGroups": ["apps"], "resources": ["deployments"], "verbs": ["get", "list"]}]
    assert binding["subjects"] == list(FIXED_SUBJECTS)
    assert binding["roleRef"] == {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": grant.role_name}
    assert role["metadata"]["annotations"][CONFIRMED_UNTIL_ANNOTATION] == "2026-08-16T00:02:00Z"


def test_rule_validation_rejects_wildcards_and_rbac_management() -> None:
    with pytest.raises(ValueError, match="wildcards"):
        PolicyRule(api_groups=("",), resources=("*",), verbs=("get",))
    with pytest.raises(ValueError, match="RBAC"):
        PolicyRule(api_groups=("rbac.authorization.k8s.io",), resources=("roles",), verbs=("create",))


@pytest.mark.asyncio
async def test_db_outage_reaps_expired_confirmation_deadline() -> None:
    stale = cast(dict[str, Any], role_binding_manifest(_grant(), confirmed_until=NOW - datetime.timedelta(seconds=1)))
    access = FakeAccess([stale])
    await LeaseReconciler(config=CONFIG, grants=cast(GrantStore, FakeGrants([], fails=True)), access=access).reconcile_once(now=NOW)
    assert access.deleted == [("target", _grant().role_name)]


@pytest.mark.asyncio
async def test_active_lease_is_projected_and_orphan_is_deleted() -> None:
    orphan = cast(dict[str, Any], role_binding_manifest(_grant(), confirmed_until=NOW + datetime.timedelta(minutes=2)))
    orphan["metadata"]["name"] = "haku-jit-orphan"
    grants, access = FakeGrants([_grant()]), FakeAccess([orphan])
    await LeaseReconciler(config=CONFIG, grants=cast(GrantStore, grants), access=access).reconcile_once(now=NOW)
    assert access.applied == [_grant()]
    assert grants.activated == [_grant().lease_id]
    assert access.deleted == [("target", "haku-jit-orphan")]
