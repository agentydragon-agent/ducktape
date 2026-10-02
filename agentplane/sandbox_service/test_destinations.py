"""Authorization and incarnation checks through real Kubernetes clients, without the app."""

from uuid import uuid4

import pytest
import pytest_bazel
from kubernetes_asyncio import client as k8s_client

from agentplane.sandbox_service.destinations import (
    DestinationDeniedError,
    DestinationResolver,
    DestinationUnavailableError,
    SessionDestination,
)
from agentplane.sandbox_service.inventory import SandboxNotFoundError
from agentplane.sandbox_service.testing.kubernetes import ACCOUNT, SANDBOX, SANDBOX_UID, Cluster
from agentplane.subjects import ServiceAccountRef
from agentplane.testing.fake_apiserver import SANDBOX_NAMESPACE
from agentplane.workload_auth.principal import WorkloadPrincipal
from util.agent_sandbox import SANDBOXES_PLURAL


@pytest.fixture
def destination() -> SessionDestination:
    return SessionDestination(
        owner=ServiceAccountRef(namespace=SANDBOX_NAMESPACE, name=ACCOUNT),
        sandbox=SANDBOX,
        sandbox_uid=SANDBOX_UID,
        session_id="test-session",
    )


@pytest.fixture
def principal() -> WorkloadPrincipal:
    return WorkloadPrincipal(
        namespace=SANDBOX_NAMESPACE,
        service_account_name=ACCOUNT,
        service_account_subject=f"system:serviceaccount:{SANDBOX_NAMESPACE}:{ACCOUNT}",
        pod_name="test-caller-pod",
        pod_uid="test-caller-pod-uid",
    )


@pytest.fixture
def resolver(cluster: Cluster) -> DestinationResolver:
    return DestinationResolver(cluster.inventory, k8s_client.CoreV1Api(cluster.api), 7000)


async def test_resolves_by_explicit_session_not_calling_pod(
    resolver: DestinationResolver, principal: WorkloadPrincipal, destination: SessionDestination
) -> None:
    resolved = await resolver.resolve(principal, destination)
    assert resolved.target == "127.0.0.1:7000"
    assert resolved.pod_uid == "test-pod-uid"


async def test_cannot_claim_another_owner(
    resolver: DestinationResolver, principal: WorkloadPrincipal, destination: SessionDestination, cluster: Cluster
) -> None:
    forged = destination.model_copy(update={"owner": ServiceAccountRef(namespace=SANDBOX_NAMESPACE, name="test-other")})
    with pytest.raises(DestinationDeniedError):
        await resolver.resolve(principal, forged)
    assert cluster.fake.pod_reads == 0


async def test_stale_sandbox_uid_is_not_rebound(
    resolver: DestinationResolver, principal: WorkloadPrincipal, destination: SessionDestination
) -> None:
    with pytest.raises(SandboxNotFoundError):
        await resolver.resolve(principal, destination.model_copy(update={"sandbox_uid": uuid4()}))


@pytest.mark.parametrize("field", ["controller", "uid", "name", "kind", "apiVersion"])
async def test_rejects_unverified_pod_owner(
    resolver: DestinationResolver,
    principal: WorkloadPrincipal,
    destination: SessionDestination,
    cluster: Cluster,
    field: str,
) -> None:
    cluster.fake.pods[SANDBOX]["metadata"]["ownerReferences"][0][field] = (
        False if field == "controller" else "test-foreign"
    )
    with pytest.raises(DestinationUnavailableError):
        await resolver.resolve(principal, destination)


async def test_rejects_pod_running_as_another_account(
    resolver: DestinationResolver, principal: WorkloadPrincipal, destination: SessionDestination, cluster: Cluster
) -> None:
    cluster.fake.pods[SANDBOX]["spec"]["serviceAccountName"] = "test-other"
    with pytest.raises(DestinationUnavailableError):
        await resolver.resolve(principal, destination)


async def test_suspension_and_deletion_are_unavailable_not_removal(
    resolver: DestinationResolver, principal: WorkloadPrincipal, destination: SessionDestination, cluster: Cluster
) -> None:
    stored = cluster.fake.objects[SANDBOXES_PLURAL][SANDBOX]
    stored["spec"]["operatingMode"] = "Suspended"
    with pytest.raises(DestinationUnavailableError):
        await resolver.resolve(principal, destination)
    stored["spec"]["operatingMode"] = "Running"
    stored["metadata"]["deletionTimestamp"] = "2026-09-01T12:00:00Z"
    with pytest.raises(DestinationUnavailableError):
        await resolver.resolve(principal, destination)


async def test_successor_pod_same_sandbox_and_account_keeps_destination(
    resolver: DestinationResolver, principal: WorkloadPrincipal, destination: SessionDestination, cluster: Cluster
) -> None:
    cluster.fake.pods[SANDBOX]["metadata"]["uid"] = "test-successor-pod"
    cluster.fake.pods[SANDBOX]["status"]["podIP"] = "::1"
    resolved = await resolver.resolve(principal, destination)
    assert resolved.pod_uid == "test-successor-pod"
    assert resolved.target == "[::1]:7000"


async def test_trusted_service_still_must_name_the_verified_owner(
    destination: SessionDestination, cluster: Cluster
) -> None:
    service = WorkloadPrincipal(
        namespace=SANDBOX_NAMESPACE,
        service_account_name="test-notifications",
        service_account_subject=f"system:serviceaccount:{SANDBOX_NAMESPACE}:test-notifications",
        pod_name="test-notifications-pod",
        pod_uid="test-notifications-pod-uid",
    )
    resolver = DestinationResolver(
        cluster.inventory, k8s_client.CoreV1Api(cluster.api), 7000, frozenset({service.account})
    )
    assert await resolver.resolve(service, destination)
    forged = destination.model_copy(update={"owner": ServiceAccountRef(namespace=SANDBOX_NAMESPACE, name="test-other")})
    with pytest.raises(SandboxNotFoundError):
        await resolver.resolve(service, forged)


if __name__ == "__main__":
    pytest_bazel.main()
