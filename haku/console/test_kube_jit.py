from __future__ import annotations

import datetime
from collections.abc import Sequence
from typing import Any, cast
from uuid import UUID

import pytest

from haku.console.kube_jit import (
    CONFIRMED_UNTIL_ANNOTATION,
    FIXED_SUBJECTS,
    AccessProfile,
    Grant,
    KubeJitConfig,
    KubernetesAccessGrantState,
    LeaseReconciler,
    RoleBindingClient,
    role_binding_manifest,
)

NOW = datetime.datetime(2026, 8, 16, tzinfo=datetime.UTC)
PROFILE = AccessProfile(
    id="readonly",
    description="reviewed read-only access",
    cluster_role="haku-jit-readonly",
    namespaces=("target",),
    max_duration_seconds=600,
)


def _grant(*, state: KubernetesAccessGrantState = KubernetesAccessGrantState.ACTIVE) -> Grant:
    return Grant(
        lease_id=UUID("11111111-1111-1111-1111-111111111111"),
        tool_call_id="tc_test",
        operator_id=UUID("22222222-2222-2222-2222-222222222222"),
        requester="haku",
        profile_id=PROFILE.id,
        profile_hash=PROFILE.revision_hash,
        namespace="target",
        cluster_role=PROFILE.cluster_role,
        issued_at=NOW,
        expires_at=NOW + datetime.timedelta(minutes=10),
        state=state,
    )


class FakeGrants:
    def __init__(self, grants: list[Grant], *, fails: bool = False) -> None:
        self.grants = grants
        self.fails = fails
        self.activated: list[UUID] = []

    async def active(self, *, now: datetime.datetime) -> list[Grant]:
        if self.fails:
            raise ConnectionError("Console database unavailable")
        return self.grants

    async def create(self, **kwargs: Any) -> Grant:
        raise AssertionError(f"unexpected create: {kwargs}")

    async def revoke(self, **kwargs: Any) -> Grant:
        raise AssertionError(f"unexpected revoke: {kwargs}")

    async def get(self, lease_id: UUID) -> Grant | None:
        return next((grant for grant in self.grants if grant.lease_id == lease_id), None)

    async def expire_due(self, *, now: datetime.datetime) -> None:
        pass

    async def activate(self, *, lease_id: UUID) -> None:
        self.activated.append(lease_id)


class FakeBindings(RoleBindingClient):
    def __init__(self, bindings: list[dict[str, Any]] | None = None) -> None:
        self.bindings = bindings or []
        self.applied: list[Grant] = []
        self.deleted: list[tuple[str, str]] = []

    async def apply(self, grant: Grant, *, confirmed_until: datetime.datetime) -> None:
        self.applied.append(grant)

    async def delete(self, *, namespace: str, name: str) -> None:
        self.deleted.append((namespace, name))

    async def managed(self, namespaces: Sequence[str]) -> list[dict[str, object]]:
        return self.bindings

    async def aclose(self) -> None:
        pass


def test_manifest_pins_the_fixed_cohort_and_profile_revision() -> None:
    grant = _grant()
    manifest = cast(dict[str, Any], role_binding_manifest(grant, confirmed_until=NOW + datetime.timedelta(minutes=2)))

    assert manifest["subjects"] == list(FIXED_SUBJECTS)
    assert manifest["roleRef"] == {
        "apiGroup": "rbac.authorization.k8s.io",
        "kind": "ClusterRole",
        "name": "haku-jit-readonly",
    }
    assert manifest["metadata"]["annotations"][CONFIRMED_UNTIL_ANNOTATION] == "2026-08-16T00:02:00Z"


@pytest.mark.asyncio
async def test_reconciler_deletes_unconfirmed_binding_when_authority_is_down() -> None:
    stale = role_binding_manifest(_grant(), confirmed_until=NOW - datetime.timedelta(seconds=1))
    grants = FakeGrants([], fails=True)
    bindings = FakeBindings([stale])
    reconciler = LeaseReconciler(
        config=KubeJitConfig(profiles=(PROFILE,), confirmation_window_seconds=120),
        grants=grants,
        role_bindings=bindings,
    )

    await reconciler.reconcile_once(now=NOW)

    assert bindings.deleted == [("target", "haku-jit-11111111111111111111111111111111")]
    assert bindings.applied == []


@pytest.mark.asyncio
async def test_reconciler_projects_active_lease_and_deletes_orphan() -> None:
    orphan = cast(dict[str, Any], role_binding_manifest(_grant(), confirmed_until=NOW + datetime.timedelta(minutes=2)))
    orphan["metadata"]["name"] = "haku-jit-orphan"
    grants = FakeGrants([_grant()])
    bindings = FakeBindings([orphan])
    reconciler = LeaseReconciler(
        config=KubeJitConfig(profiles=(PROFILE,), confirmation_window_seconds=120),
        grants=grants,
        role_bindings=bindings,
    )

    await reconciler.reconcile_once(now=NOW)

    assert bindings.applied == [_grant()]
    assert grants.activated == [_grant().lease_id]
    assert bindings.deleted == [("target", "haku-jit-orphan")]
